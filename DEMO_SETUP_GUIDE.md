# Demo Environment Setup Guide

## Overview

This guide walks through setting up the sandboxed demo environment for Phantom Dev. **Critical rule: Never use real accounts.** All demo scenarios use isolated, pre-seeded sandbox accounts.

---

## Step 1: Jira Sandbox Setup

### 1.1 Create Jira Cloud Account
1. Go to https://www.atlassian.com/software/jira/free
2. Click **"Get it free"**
3. Sign up with a dedicated email (e.g., `phantomdev.demo@gmail.com` or create a new one)
4. Choose **"Cloud"** (not Server)
5. Complete the setup wizard

### 1.2 Create Demo Project
1. After login, click **"Create project"**
2. Choose **"Scrum"** template
3. Name it: **"Phantom Demo"**
4. Set project key: **"PD"** (or auto-generated)

### 1.3 Pre-seed Tickets
Create **10 tickets total**:

**5 tickets tagged "Q1":**
1. "Fix login button not responding" — Status: To Do, Priority: High
2. "Add dark mode toggle" — Status: In Progress, Priority: Medium
3. "Update user dashboard layout" — Status: To Do, Priority: Low
4. "Resolve API timeout issue" — Status: To Do, Priority: High
5. "Implement search functionality" — Status: Done, Priority: Medium

**5 tickets tagged "Q2":**
6. "Refactor authentication module" — Status: To Do, Priority: High
7. "Add email notifications" — Status: To Do, Priority: Medium
8. "Optimize database queries" — Status: In Progress, Priority: High
9. "Create user onboarding flow" — Status: To Do, Priority: Low
10. "Fix mobile responsive layout" — Status: To Do, Priority: Medium

**How to add tags:**
- When creating/editing a ticket, look for **"Labels"** field
- Add label: `Q1` or `Q2`
- Save the ticket

### 1.4 Keep Session Active
1. Check **"Remember me"** when logging in
2. Verify session lasts 24+ hours (test by closing browser and reopening)
3. Bookmark the project board URL for instant navigation
4. **Important:** Log in 1 hour before demo recording to ensure session is fresh

---

## Step 2: Google Sheets Sandbox Setup

### 2.1 Create Dedicated Google Account
1. Go to https://accounts.google.com/signup
2. Create account: `phantomdev.demo@gmail.com` (or similar)
3. Complete verification

### 2.2 Create Bug Tracker Spreadsheet
1. Go to https://sheets.google.com
2. Click **"Blank"** to create new spreadsheet
3. Rename it: **"Bug Tracker"**
4. Set up headers in Row 1:
   - **A1:** `Ticket ID`
   - **B1:** `Title`
   - **C1:** `Status`
   - **D1:** `Priority`
   - **E1:** `Date Added`

### 2.3 Pre-fill Sample Data
Add **3 rows** of sample data:

| Ticket ID | Title | Status | Priority | Date Added |
|-----------|-------|--------|----------|------------|
| PD-001 | Sample bug from previous sprint | Resolved | High | 2026-03-01 |
| PD-002 | UI improvement suggestion | Open | Medium | 2026-03-05 |
| PD-003 | Performance optimization | In Progress | Low | 2026-03-08 |

### 2.4 Keep Logged In
1. Use a **dedicated Chrome profile** for demo
2. Keep the account logged in
3. Bookmark the spreadsheet URL
4. **Important:** Verify login 1 hour before demo

---

## Step 3: Slack Sandbox Setup

### 3.1 Create Slack Workspace
1. Go to https://slack.com/create
2. Enter workspace name: **"Phantom Demo Workspace"**
3. Enter your email (use the demo Google account)
4. Complete setup wizard

### 3.2 Create Channel
1. Click **"Channels"** in sidebar
2. Click **"+"** to create channel
3. Name: **"#bug-reports"**
4. Make it **public** (or private, your choice)
5. Click **"Create"**

### 3.3 Add Dummy Messages
Post a few messages to make channel look active:
- "Bug PD-001 has been resolved"
- "New bug reported: PD-002"
- "Following up on PD-003"

### 3.4 Keep Logged In
1. Use the **same Chrome profile** as Sheets
2. Keep workspace logged in
3. Bookmark the channel URL
4. **Important:** Verify login 1 hour before demo

---

## Step 4: Demo Desktop Setup

### 4.1 Create Clean User Account (macOS)
1. System Settings → Users & Groups
2. Click **"+"** to add new user
3. Name: **"Phantom Demo"** (or similar)
4. Set as **Standard** user (not Admin)
5. Log out and log into this account

### 4.2 Disable All Notifications
**System-level:**
- System Settings → Notifications
- Turn off **all** notifications (or set Do Not Disturb)

**Browser-level:**
- Chrome: Settings → Privacy and security → Site settings → Notifications → Block
- Firefox: Settings → Privacy & Security → Permissions → Notifications → Block

**App-level:**
- Disable notifications for Slack, email, calendar, etc.

### 4.3 Desktop Appearance
1. **Wallpaper:** Set solid dark color (e.g., `#1a1a1a` or `#000000`)
2. **Dock:** Show only essential apps (Chrome, Finder, System Settings)
3. **Menu bar:** Hide unnecessary icons

### 4.4 Screen Resolution
1. System Settings → Displays
2. Set resolution: **1920x1080** (or native if different, but keep consistent)
3. **Important:** Use this exact resolution for all demo recordings

### 4.5 Disable Screen Saver & Auto-lock
1. System Settings → Lock Screen
2. Set **"Require password after screen saver"** to **Never** (or very long time)
3. Set **"Start screen saver after"** to **Never**

### 4.6 Pin Demo Apps
1. Open Chrome with **3 tabs**:
   - Tab 1: Jira project board
   - Tab 2: Google Sheets "Bug Tracker"
   - Tab 3: Slack #bug-reports channel
2. Pin Chrome to Dock
3. Close all other apps

---

## Step 5: Pre-Demo Checklist

**1 hour before recording:**

- [ ] Jira session is active (open and verify)
- [ ] Google Sheets session is active (open and verify)
- [ ] Slack session is active (open and verify)
- [ ] All notifications disabled
- [ ] Screen resolution set to 1920x1080
- [ ] Screen saver disabled
- [ ] Only demo apps open (Chrome with 3 tabs)
- [ ] Bookmarks ready for quick navigation
- [ ] Test voice command: "Hey Phantom, test connection"
- [ ] Verify dashboard shows task

---

## Step 6: Practice Runs

**Before recording, practice 10+ times:**

1. Say: **"Hey Phantom, take the top 5 bugs from Jira tagged Q1, add them to our tracking spreadsheet in Google Sheets, and post a summary in Slack."**
2. Watch executor perform actions (when connected)
3. Verify all data appears correctly
4. Note any issues and fix them

**Practice until:**
- ✅ No unexpected dialogs/popups
- ✅ All apps load quickly
- ✅ Voice command is recognized correctly
- ✅ Executor completes task without errors

---

## Troubleshooting

### Session Expired
- **Solution:** Log in 1 hour before recording, use "Remember me" on all accounts

### Unexpected Popup/Dialog
- **Solution:** Practice more, identify triggers, disable them in settings

### Apps Not Loading
- **Solution:** Pre-open all apps 5 minutes before recording, keep them in background

### Voice Not Recognized
- **Solution:** Practice the exact phrase, speak clearly, check microphone permissions

---

## Backup Plan

If something fails during recording:
1. **Stop immediately**
2. Fix the issue
3. Re-record from the beginning of that segment
4. **Never cut mid-action** — demo must be seamless

Keep backup screenshots of each app's expected state for quick reset.

---

## Next Steps

After setup is complete:
1. ✅ Test voice → task → dashboard flow (already done)
2. ⏳ Wait for executor to be connected
3. ⏳ Full integration testing (Day 6)
4. ⏳ Record demo video (Day 7-8)
