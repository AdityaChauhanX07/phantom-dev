# Set DRY_RUN = True in orchestrator.py to test without actual clicks

import json
from orchestrator import TaskOrchestrator

goal = "Open Chrome and search for Gemini Live Agent Challenge"

orchestrator = TaskOrchestrator(goal)
final_state = orchestrator.run()

print(json.dumps(final_state, indent=2))
