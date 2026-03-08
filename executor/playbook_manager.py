"""
PlaybookManager — saves and loads successful task traces.

Successful task runs are persisted as JSON playbooks and can be retrieved
via fuzzy goal matching (Jaccard word overlap) so Gemini can use prior
experience as guidance when planning similar tasks.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PLAYBOOKS_DIR = Path("executor/playbooks")


def _slugify(text: str) -> str:
    """Lowercase, spaces → hyphens, strip everything except [a-z0-9-]."""
    text = text.lower().strip()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _goal_words(goal: str) -> set[str]:
    """Return non-trivial lowercase words from a goal string."""
    stopwords = {"a", "an", "the", "and", "or", "to", "in", "on", "at", "of", "for"}
    return {w for w in re.findall(r"[a-z]+", goal.lower()) if w not in stopwords}


class PlaybookManager:
    """
    Saves and loads successful task traces (playbooks).

    Playbooks are stored as JSON files in ``playbooks_dir``.  Each file holds
    the goal, the completed steps, and metadata that lets the orchestrator
    inject prior experience into Gemini prompts.

    Usage::

        pm = PlaybookManager()
        pm.save(final_state)          # persists if task completed
        pb = pm.find("open chrome")   # fuzzy goal match
        if pb:
            hint = pm.format_for_prompt(pb)
    """

    def __init__(self):
        self.playbooks_dir = PLAYBOOKS_DIR
        self.playbooks_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("[PlaybookManager] playbooks_dir=%s", self.playbooks_dir.resolve())

    # ------------------------------------------------------------------ #

    def save(self, task_state: dict) -> str:
        """
        Persist a completed task trace as a playbook JSON file.

        Only saves when ``task_state["status"] == "completed"`` and at least
        one step was completed.  Silently returns ``""`` otherwise.

        Args:
            task_state: Final state dict returned by ``TaskOrchestrator.run()``.

        Returns:
            Absolute path of the saved file, or ``""`` if nothing was saved.
        """
        if task_state.get("status") != "completed":
            logger.debug("[PlaybookManager.save] Skipping — status=%s", task_state.get("status"))
            return ""

        steps_completed = task_state.get("steps_completed", [])
        if not steps_completed:
            logger.debug("[PlaybookManager.save] Skipping — no completed steps.")
            return ""

        total_steps = len(steps_completed) + len(task_state.get("steps_failed", []))
        success_rate = len(steps_completed) / total_steps if total_steps else 1.0

        playbook = {
            "goal": task_state["goal"],
            "saved_at": datetime.utcnow().isoformat(),
            "steps": steps_completed,
            "correction_history": task_state.get("correction_history", []),
            "success_rate": round(success_rate, 4),
        }

        slug = _slugify(task_state["goal"])[:60]   # cap slug length
        uid = uuid.uuid4().hex[:8]
        filename = f"{slug}-{uid}.json"
        filepath = self.playbooks_dir / filename

        with filepath.open("w", encoding="utf-8") as fh:
            json.dump(playbook, fh, indent=2, ensure_ascii=False)

        logger.info("[PlaybookManager] Playbook saved: %s", filename)
        return str(filepath)

    # ------------------------------------------------------------------ #

    def find(self, goal: str) -> dict | None:
        """
        Find the best-matching playbook for *goal* using Jaccard word overlap.

        Similarity = |goal_words ∩ saved_words| / |goal_words ∪ saved_words|.
        Returns the highest-scoring playbook if its score exceeds 0.4,
        otherwise returns ``None``.

        Args:
            goal: The goal string to match against stored playbooks.

        Returns:
            Playbook dict (as saved) or ``None``.
        """
        query_words = _goal_words(goal)
        if not query_words:
            return None

        best_score = 0.0
        best_playbook = None
        best_filename = ""

        for path in self.playbooks_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    playbook = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[PlaybookManager.find] Could not load %s: %s", path.name, exc)
                continue

            saved_words = _goal_words(playbook.get("goal", ""))
            union = query_words | saved_words
            if not union:
                continue

            score = len(query_words & saved_words) / len(union)
            if score > best_score:
                best_score = score
                best_playbook = playbook
                best_filename = path.name

        if best_score > 0.4 and best_playbook is not None:
            logger.info(
                "[PlaybookManager] Playbook match: %s (similarity=%.2f)",
                best_filename,
                best_score,
            )
            return best_playbook

        logger.debug(
            "[PlaybookManager.find] No match above threshold (best=%.2f).", best_score
        )
        return None

    # ------------------------------------------------------------------ #

    def format_for_prompt(self, playbook: dict) -> str:
        """
        Format a playbook as a concise hint string for injection into Gemini prompts.

        Args:
            playbook: Dict returned by :meth:`find`.

        Returns:
            Multi-line string summarising the playbook steps.
        """
        goal = playbook.get("goal", "unknown goal")
        steps = playbook.get("steps", [])

        lines = [f"LEARNED PLAYBOOK for similar task '{goal}':"]
        for step in steps:
            step_num = step.get("step", "?")
            description = step.get("description", "")
            # Best-effort: show action type if recorded, otherwise just description
            action_type = step.get("action_type") or step.get("action", {}).get("type", "unknown")
            lines.append(f"  Step {step_num}: {description} → Action taken: {action_type}")

        lines.append(
            "Use this as guidance but adapt to what you currently see on screen."
        )
        return "\n".join(lines)
