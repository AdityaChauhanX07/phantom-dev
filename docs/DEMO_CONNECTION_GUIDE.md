# How to Connect Everything and Test the Demo

## Current Status

**What is already working:**
- Voice recognition → task creation → dashboard displays the task
- Jira, Sheets, Slack accounts created

**Pending:**
- Executor from your partner (will perform real on-screen actions)

---

## Step 1: Verify All Accounts Are Logged In

### 1.1 Jira
1. Open Jira in the browser
2. Confirm you are logged in (no password prompt)
3. Open the "Phantom Demo" project
4. Verify you can see 10 tickets (5 tagged Q1, 5 tagged Q2)
5. **Bookmark:** Save the project URL

### 1.2 Google Sheets
1. Open Google Sheets
2. Confirm you are logged in
3. Open the "Bug Tracker" spreadsheet
4. Verify headers are present (Ticket ID, Title, Status, Priority, Date Added)
5. Verify there are 3 rows of data
6. **Bookmark:** Save the spreadsheet URL

### 1.3 Slack
1. Open Slack in the browser
2. Confirm you are logged in to the "Phantom Demo Workspace"
3. Open the #bug-reports channel
4. Verify there are several messages
5. **Bookmark:** Save the channel URL

---

## Step 2: Prepare the Browser for Demo

### 2.1 Create a Separate Chrome Profile (Recommended)

1. Open Chrome
2. Click the profile icon (top right)
3. Click "Add" → "Create new profile"
4. Name it "Phantom Demo"
5. In this profile:
   - Log in to Jira
   - Log in to Google Sheets
   - Log in to Slack
   - Open all 3 tabs (Jira, Sheets, Slack)
   - Pin Chrome to the Dock

### 2.2 Or Use Your Current Profile

If you do not want to create a new profile:
1. Open 3 tabs in Chrome:
   - Tab 1: Jira project
   - Tab 2: Google Sheets "Bug Tracker"
   - Tab 3: Slack #bug-reports
2. Pin Chrome to the Dock

---

## Step 3: Testing Voice Commands (Now)

**While the executor is not connected, you can test the voice flow:**

### Test 1: Simple Command
1. Open `http://localhost:3000/voice-test.html`
2. Say: **"Hey Phantom, take Q1 tickets from Jira and add them to the tracking sheet"**
3. Verify:
   - The log shows: `HTTP TASK DETECTED: ...`
   - A task appears in the dashboard

### Test 2: Full Command (as in the demo)
1. Say: **"Hey Phantom, take the top 5 bugs from Jira tagged Q1, add them to our tracking spreadsheet in Google Sheets, and post a summary in Slack"**
2. Verify that the task is created with the correct goal

**Note:** The executor is not connected yet, so the task will remain in `queued` status and will not be executed. This is expected.

---

## Step 4: What Happens When the Executor Connects

### When your partner connects the executor:

1. **Executor will connect to:** `wss://phantom-agent-874381233509.us-central1.run.app/ws/executor`

2. **When you say a voice command:**
   - Task is created (as now)
   - Executor receives the task via WebSocket
   - Executor starts performing on-screen actions:
     - Opens Jira
     - Finds tickets tagged Q1
     - Copies the data
     - Switches to Google Sheets
     - Inserts data into the spreadsheet
     - Switches to Slack
     - Posts a message in #bug-reports
   - Executor sends results back
   - Dashboard shows status `running` → `completed`

3. **You will see:**
   - In dashboard: task status changes from `queued` to `running`, then to `completed`
   - On screen: real actions (clicks, text input, switching between apps)
   - In Activity Feed: `screenshot` and `task_result` events

---

## Step 5: Preparing for the Full Test

### When the executor is ready:

1. **Verify all accounts are logged in:**
   - Jira: open the project, check tickets
   - Sheets: open the spreadsheet, check headers
   - Slack: open the #bug-reports channel

2. **Close all unnecessary windows/tabs:**
   - Keep only 3 tabs (Jira, Sheets, Slack)
   - Close all other apps

3. **Disable notifications:**
   - macOS: System Settings → Notifications → enable Do Not Disturb
   - Or disable all notifications

4. **Start the dashboard:**
   ```bash
   cd dashboard
   npm run dev
   ```

5. **Open in browser:**
   - Dashboard: `http://localhost:3000`
   - Voice Test: `http://localhost:3000/voice-test.html`

6. **Verify the executor is connected:**
   - Dashboard should show: **"1 executor connected"** (green status)
   - If you see "No executor" — executor is not connected yet

---

## Step 6: Full Test (When Executor is Ready)

### Test scenario:

1. **Say the voice command:**
   "Hey Phantom, take the top 5 bugs from Jira tagged Q1, add them to our tracking spreadsheet in Google Sheets, and post a summary in Slack"

2. **Watch:**
   - Dashboard: task appears, status changes to `running`
   - On screen: executor opens Jira, searches for tickets, copies data
   - Executor switches to Sheets, inserts data
   - Executor switches to Slack, posts a message
   - Dashboard: status changes to `completed`

3. **Verify the result:**
   - New rows with Jira data appear in Google Sheets
   - A summary message appears in Slack #bug-reports

---

## What to Do Right Now

### Now (executor not yet connected):

1. **Verify all accounts are logged in:**
   - Open Jira → check tickets
   - Open Sheets → check spreadsheet
   - Open Slack → check channel

2. **Test voice commands:**
   - Say a few commands
   - Confirm tasks are being created
   - Verify the goal is recognized correctly

3. **Prepare the browser:**
   - Open all 3 tabs (Jira, Sheets, Slack)
   - Pin Chrome to the Dock
   - Close all unnecessary windows

4. **Wait for the executor from your partner**

### When the executor is ready:

1. Verify the executor is connected (dashboard should show "1 executor connected")
2. Run the full test (see Step 6 above)
3. If something is not working — check Cloud Run logs

---

## Troubleshooting

### Task is created but executor does not execute

**Cause:** Executor is not connected or did not receive the task

**Solution:**
- Check the dashboard: is "1 executor connected" shown?
- If not — your partner has not connected the executor yet
- If yes — check Cloud Run logs

### Executor executes but data does not appear

**Cause:** Executor cannot find elements on screen

**Solution:**
- Make sure all tabs are open and visible
- Verify that Jira tickets have the correct labels (Q1, Q2)
- Verify that the Sheets table has the correct headers

### Voice command is not recognized

**Cause:** Phrase is too complex or unclear

**Solution:**
- Speak clearly and slowly
- Use the phrase: "Hey Phantom, take the top 5 bugs from Jira tagged Q1, add them to our tracking spreadsheet in Google Sheets, and post a summary in Slack"
- If it still does not work — simplify: "Hey Phantom, move Q1 tickets to sheet"

---

## Next Steps

1. Check all accounts (Jira, Sheets, Slack)
2. Test voice commands
3. Wait for the executor from your partner
4. Run the full end-to-end test
5. Record the demo video

**Ready to test?** Let us know when your partner connects the executor and we will run the full test.
