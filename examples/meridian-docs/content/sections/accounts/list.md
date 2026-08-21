---
id: accounts.list
title: Accounts List
status: draft
screens:
- accounts.list
---

Every account in the workspace, searchable and filterable by status.

```columns
- column: Name
  description: The account's display name, with its plan beneath it
- column: Account ID
  description: The immutable identifier used in exports and in the API
- column: Region
  description: Where this account's events are processed
- column: Plan
  description: Starter, Growth or Scale
- column: Status
  description: Live, On hold or Disabled
- column: OWNER
```

Filter the list with the status buttons above the table.

```actions
- action: New account
  description: Opens the form for creating an account in this workspace
- action: Export
  description: Downloads the current view as a file
```

![The accounts list](accounts-list-1.png)
