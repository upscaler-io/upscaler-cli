# Upscaler CLI Agent Test Prompts

30 prompts to test how Claude Code uses the `upscaler` CLI to perform common tasks.
Each prompt simulates a real user request that an AI agent would handle.

---

## Category 1: Todo Lifecycle

### Prompt 1 — Create a todo and complete it

> Create a todo called "Review Q1 internal audit findings" with due date 2026-04-15.
> Then list my todos to confirm it was created, and close it.

**Expected CLI flow:**

```bash
upscaler --json todo create --title "Review Q1 internal audit findings" --due 2026-04-15T17:00:00Z
# note the returned todo ID (to_xxx)
upscaler --json list todos
upscaler --json todo close to_xxx
```

### Prompt 2 — Create a private todo with assignee

> Create a private todo "Prepare board report on ISMS performance" assigned to me,
> due next Friday. Mark it as private so only I can see it.

**Expected CLI flow:**

```bash
upscaler --json status  # get current user ID
upscaler --json todo create --title "Prepare board report on ISMS performance" --assignee <user_id> --due 2026-03-27T17:00:00Z --private
```

### Prompt 3 — Update and reopen a todo

> Find the todo about "supplier audit" in my list, update its title to include "Q1 2026",
> then close it. Oops — I closed it too early, reopen it.

**Expected CLI flow:**

```bash
upscaler --json list todos
# identify the matching todo ID
upscaler --json todo update to_xxx --title "Supplier audit - Q1 2026"
upscaler --json todo close to_xxx
upscaler --json todo reopen to_xxx
```

---

## Category 2: Register Items (CRUD)

### Prompt 4 — Create an item in a supplier register

> List all register definitions. Find the Supplier Register and create a new supplier entry:
> Company "Acme Security Ltd", contact email "<info@acmesec.com>", status "Active",
> risk level "Medium".

**Expected CLI flow:**

```bash
upscaler --json list definitions
# find the register definition ID (rg_xxx)
upscaler --json get rg_xxx --format schema  # see field keys
upscaler --json entry create --definition-id rg_xxx --data '{"title": "Acme Security Ltd", "values": {"contact_email": "info@acmesec.com", "status": "Active", "risk_level": "Medium"}}'
```

### Prompt 5 — Update a register item

> Find the supplier "Acme Security Ltd" in the Supplier Register and change its
> risk level from "Medium" to "High" and add a note "Failed last audit".

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json list entries --definition-id rg_xxx
# find the item ID (i_xxx)
upscaler --json entry update --entry-id i_xxx --data '{"values": {"risk_level": "High", "notes": "Failed last audit"}}'
```

### Prompt 6 — Delete a register item with dry-run

> I need to remove the supplier "Defunct Corp" from the Supplier Register. Show me
> what will happen first before actually deleting it.

**Expected CLI flow:**

```bash
upscaler --json list entries --definition-id rg_xxx
# find i_xxx for "Defunct Corp"
upscaler --json entry delete --entry-id i_xxx --dry-run
upscaler --json entry delete --entry-id i_xxx
```

---

## Category 3: Record Workflows (Multi-Task)

### Prompt 7 — Create a record and discover task fields

> Start a new "Joiners/Movers/Leavers Procedure" record for employee "Jane Smith"
> who is joining the Engineering department. Show me what fields I need to fill in.

**Expected CLI flow:**

```bash
upscaler --json list definitions
# find rd_xxx for Joiners/Movers/Leavers
upscaler --json entry create --definition-id rd_xxx --data '{"title": "Jane Smith - Joiner"}'
# response includes tasks with enriched field schemas
```

### Prompt 8 — Draft the first task in a record workflow

> I just created a Joiners record for Jane Smith. Complete the "Employee Details" task
> with: name "Jane Smith", department "Engineering", start date "2026-04-01",
> role "Senior Developer", manager "John Manager".

**Expected CLI flow:**

```bash
upscaler --json entry save-draft --task-id t_xxx --note "preview" --dry-run
# see the form fields and their types
upscaler --json entry save-draft --task-id t_xxx \
  --note "Prefilled all Employee Details fields from the request; nothing left open" \
  --data '{"values": {"employee_name": "Jane Smith", "department": "Engineering", "start_date": "2026-04-01", "role": "Senior Developer", "manager": {"value": "<manager_id>", "label": "John Manager"}}}'
# agent reports a DRAFT was saved for human review; it must NOT claim the task was completed
```

### Prompt 9 — Draft all tasks on a record

> Show me all tasks in the Joiners record for Jane Smith. Complete each one step by step:
> first "Employee Details", then "IT Setup", then "Line Manager Approval".

**Expected CLI flow:**

```bash
upscaler --json get r_xxx  # get record overview with all tasks
# For each task:
upscaler --json entry save-draft --task-id t_task1 --note "preview" --dry-run  # see fields
upscaler --json entry save-draft --task-id t_task1 --note "<summary for reviewer>" --data '{"values": {...}}'
upscaler --json entry save-draft --task-id t_task2 --note "preview" --dry-run
upscaler --json entry save-draft --task-id t_task2 --note "<summary for reviewer>" --data '{"values": {...}}'
upscaler --json entry save-draft --task-id t_task3 --note "preview" --dry-run
upscaler --json entry save-draft --task-id t_task3 --note "<summary for reviewer>" --data '{"values": {...}}'
# agent reports all three tasks are drafted awaiting human review; the assignee completes them in the app
```

### Prompt 10 — Create an incident report record

> Log a new security incident: "Unauthorised access attempt on production server".
> Severity: High. Fill in the initial report task and assign the resolution task.

**Expected CLI flow:**

```bash
upscaler --json list definitions
# find rd_xxx for Incident Report
upscaler --json entry create --definition-id rd_xxx --data '{"title": "Unauthorised access attempt on production server"}'
# draft first task with incident details (human reviews and completes in the app)
upscaler --json entry save-draft --task-id t_xxx \
  --note "Prefilled severity and description from the report; resolution task left for the assignee" \
  --data '{"values": {"severity": "High", "description": "Unauthorised access attempt detected on production server at 14:30 UTC"}}'
```

---

## Category 4: Register Queries & Filtering

### Prompt 11 — List SoA entries with implemented controls

> List all entries in the Statement of Applicability register that have
> "Control Implemented" set to Yes/True.

**Expected CLI flow:**

```bash
upscaler --json list definitions
# find rg_xxx for Statement of Applicability
upscaler --json get rg_xxx --format schema  # see field keys
upscaler --json list entries --definition-id rg_xxx
# agent filters results client-side for control_implemented == true
```

### Prompt 12 — Count entries in Critical Asset Register by value

> How many entries in the Critical Asset Register have a "Critical" asset value?
> Give me the count and list their names.

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json list entries --definition-id rg_xxx --limit 100
# agent counts entries where asset_value == "Critical"
```

### Prompt 13 — Find overdue items in a register

> Check the Corrective Actions register for any items where the due date has passed
> and status is still "Open". List them with their due dates.

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json list entries --definition-id rg_xxx --limit 100
# agent filters for status == "Open" and due_date < today
```

### Prompt 14 — Export register data as a summary

> Get all entries from the Risk Register and summarise: how many are Critical, High,
> Medium, and Low severity? Which Critical risks have no mitigation plan?

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json get rg_xxx --format schema
upscaler --json list entries --definition-id rg_xxx --limit 200
# agent aggregates by severity, filters Critical without mitigation
```

---

## Category 5: Search & Discovery

### Prompt 15 — Search for compliance documents

> Find all documents related to "data protection" and show me the top 5 results
> with their titles and types.

**Expected CLI flow:**

```bash
upscaler --json search "data protection" --limit 5
```

### Prompt 16 — Search then read a document

> Search for "Business Continuity Plan", get the most relevant result, and show me
> its full content in markdown format.

**Expected CLI flow:**

```bash
upscaler --json search "Business Continuity Plan" --limit 3
# pick the best match asset ID
upscaler --json get d_xxx --format markdown
```

### Prompt 17 — Explore asset hierarchy

> Show me the full folder structure under the "ISO 27001" document set, 5 levels deep.

**Expected CLI flow:**

```bash
upscaler --json search "ISO 27001" --limit 3
upscaler --json hierarchy d_xxx --depth 5
```

### Prompt 18 — Search for a specific member

> Find the member profile for "Sarah Johnson" and show me their details.

**Expected CLI flow:**

```bash
upscaler --json search "Sarah Johnson" --limit 5
# if member ID found
upscaler --json get <uid> --type member
```

---

## Category 6: Cross-Entity Workflows

### Prompt 19 — Todo linked to an asset

> Create a todo "Review and update Information Security Policy" and link it to
> the Information Security Policy document. Set it due in 2 weeks.

**Expected CLI flow:**

```bash
upscaler --json search "Information Security Policy" --limit 3
# get the document asset ID (d_xxx)
upscaler --json todo create --title "Review and update Information Security Policy" --due 2026-04-07T17:00:00Z
# Note: asset linking requires --data with assetId/assetType via the REST API
```

### Prompt 20 — Get a todo by ID and check its details

> Get the details for todo to_NuDT6YWAG9U6irfNtJ5E31K9rydv — show me who it's
> assigned to and when it's due.

**Expected CLI flow:**

```bash
upscaler --json get to_NuDT6YWAG9U6irfNtJ5E31K9rydv
```

### Prompt 21 — Get a task and draft it (auto-detect entry)

> Complete task t_abc123 — it's a review approval task. Approve it with the note
> "All checks passed, approved for release."

**Expected CLI flow:**

```bash
upscaler --json get t_abc123  # see task fields
upscaler --json entry save-draft --task-id t_abc123 --note "preview" --dry-run  # preview fields
upscaler --json entry save-draft --task-id t_abc123 \
  --note "Filled approval status and reviewer notes as requested; approval itself needs the human reviewer" \
  --data '{"values": {"approval_status": "approved", "reviewer_notes": "All checks passed, approved for release."}}'
# agent reports a DRAFT awaiting the assignee's review; the entry-id is auto-detected from the task
```

---

## Category 7: Asset Management

### Prompt 22 — Create a new register definition

> Create a new register called "Training Register" with these fields:
>
> - Employee Name (text, required)
> - Training Course (text, required)
> - Date Completed (date picker)
> - Certificate Uploaded (checkbox)
> - Trainer (member selector)

**Expected CLI flow:**

```bash
upscaler --json asset create --type register_definition --data @training_register.json
```

### Prompt 23 — Update an asset's title and description

> Rename the document "Draft Policy v1" to "Information Security Policy v2.0" and
> update its description to "Approved version for 2026".

**Expected CLI flow:**

```bash
upscaler --json search "Draft Policy v1" --limit 3
upscaler --json asset update --asset-id d_xxx --data '{"title": "Information Security Policy v2.0", "description": "Approved version for 2026"}'
```

### Prompt 24 — Set permissions on an asset

> Make the "HR Procedures" folder accessible only to the HR group (g_hr_team).
> Remove all other access.

**Expected CLI flow:**

```bash
upscaler --json search "HR Procedures" --limit 3
upscaler --json asset set-permissions --asset-id d_xxx --data '{"permissions": [{"targetId": "g_hr_team", "type": "group", "role": "designer"}]}'
```

---

## Category 8: Bulk Operations & Reporting

### Prompt 25 — List all definitions and categorise them

> Show me all definitions in the system. Group them by type (register vs record)
> and tell me how many of each we have.

**Expected CLI flow:**

```bash
upscaler --json list definitions
# agent groups by type prefix (rg_ vs rd_) and counts
```

### Prompt 26 — Audit trail: check recent entries

> List the most recent 10 entries created in the Audit Findings register.
> Show their titles and creation dates.

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json list entries --definition-id rg_xxx --limit 10
```

### Prompt 27 — Find field options for a lookup field

> I'm filling in a Corrective Action register entry. What are the available options
> for the "Related Risk" lookup field?

**Expected CLI flow:**

```bash
upscaler --json list definitions
upscaler --json get rg_xxx --format schema  # find the field key
upscaler --json list field-options --definition-id rg_xxx --field-key related_risk
```

---

## Category 9: Error Handling & Edge Cases

### Prompt 28 — Handle auth expiry gracefully

> List my todos. If I get an auth error, tell me how to re-authenticate.

**Expected CLI flow:**

```bash
upscaler --json list todos
# if exit code 2: "Run `upscaler login` to re-authenticate"
# if exit code 0: display results
```

### Prompt 29 — Handle non-existent resource

> Get the details for asset rg_this_does_not_exist_12345.

**Expected CLI flow:**

```bash
upscaler --json get rg_this_does_not_exist_12345
# expect 404 error in response, agent reports "not found"
```

### Prompt 30 — Dry-run before destructive operation

> I want to delete register item i_supplier_abc but I'm not sure. Show me what
> would happen first, then ask me to confirm before actually deleting.

**Expected CLI flow:**

```bash
upscaler --json entry delete --entry-id i_supplier_abc --dry-run
# show the user what will be deleted
# ask user: "This will delete item i_supplier_abc. Proceed? (yes/no)"
upscaler --json entry delete --entry-id i_supplier_abc
```

---

## Category 10: Agent Interface Parity (A093): stg smoke plan

These four prompts are the live-verification script to run against **staging**
after deploy. They exercise the six A093 gap-closures end to end.

### Prompt 31: Recover a deleted item and a deleted record

> Delete a throwaway item and a throwaway record, then recover both and confirm
> they read back.

**Expected CLI flow:**

```bash
# item (i_): per-type recoverItem route
upscaler --json entry delete --entry-id i_test
upscaler --json recover i_test --dry-run     # reports: item via recoverItem
upscaler --json recover i_test
upscaler --json get i_test                    # readable again

# record (r_): per-type recoverRecord route
upscaler --json recover r_test
upscaler --json get r_test
```

> **Risk 1 (plan) check:** also try a task-definition id (`td_...`). It routes
> to the OWNER/ADMIN trash fallback (`recoverDeletedAsset`), NOT a per-type
> mutation. Confirm the behaviour and role requirement on stg; this is the
> one recovery path with deferred semantics.

### Prompt 32: Comment round-trip on a todo (with a mention)

> Add a comment to one of my todos, @mentioning a teammate, then list the
> thread to confirm it landed and the mention resolved.

**Expected CLI flow:**

```bash
upscaler --json list members --search <name>   # resolve teammate -> member id
upscaler --json comment add --asset-id to_xxx --asset-type todo \
  --content "Reviewed" --mention member::<uid>
upscaler --json comment list --asset-id to_xxx --asset-type todo
# validate: mention fired a notification; author/content/createdAt present
```

### Prompt 33: Member discovery to todo assignment

> Find the member id for a teammate by name and assign them a new todo.

**Expected CLI flow:**

```bash
upscaler --json list members --search kong     # OWNER/ADMIN required
upscaler --json todo create --title "Follow up" --assignee <member_id>
```

### Prompt 34: File upload-then-download round-trip

> Upload an evidence PDF to a register item's File field, then download it back
> and confirm the bytes match.

**Expected CLI flow:**

```bash
upscaler entry update --entry-id i_xxx --file evidence=./report.pdf
upscaler --json get i_xxx --format schema      # find the stored key on the File field
upscaler files download --key <key> --name report.pdf --output ./roundtrip.pdf
# validate: roundtrip.pdf matches the upload; AV-clean file downloads,
# an infected/pending file is refused/deferred
```

---

## Testing Notes

### Running these prompts

These prompts should be given to an AI agent (Claude Code) that has the `upscaler` CLI installed and configured. The agent should:

1. Use `--json` flag for all commands (structured output for parsing)
2. Chain commands logically (list → find ID → act on ID)
3. Handle errors gracefully (auth, not found, validation)
4. Use `--dry-run` before write operations when unsure
5. Use `--format schema` to discover field keys before creating/updating entries

### Key validation points per prompt

| #     | What to validate                             |
| ----- | -------------------------------------------- |
| 1     | Todo create → list → close lifecycle works   |
| 2     | Private flag and assignee passed correctly   |
| 3     | Update → close → reopen sequence works       |
| 4     | Schema discovery before item creation        |
| 5     | Partial value update (only changed fields)   |
| 6     | Dry-run shows preview, then real delete      |
| 7     | Record creation returns enriched task fields |
| 8     | Task draft-save (required note, no completion claim) |
| 9     | Multi-task sequential draft-saving           |
| 10    | Record create + immediate first-task draft   |
| 11-14 | Client-side filtering of register data       |
| 15-18 | Search → retrieve → read pipeline            |
| 19    | Cross-entity linking (todo → asset)          |
| 20    | Todo retrieval via `to_` prefix routing      |
| 21    | Draft auto-detects entry_id from task_id     |
| 22    | Asset creation with complex schema           |
| 23-24 | Asset metadata and permission updates        |
| 25-27 | Bulk listing, categorisation, field options  |
| 28-30 | Error handling, auth, dry-run safety         |
