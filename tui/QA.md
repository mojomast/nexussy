# nexussy TUI Manual QA

1. Start core and web:

```bash
./nexussy.sh start
```

2. Start TUI:

```bash
./nexussy.sh start-tui
```

3. Confirm the default UI is chat transcript mode, not a permanent three-column dashboard.

3a. Confirm the onboarding explains the pipeline abilities: Interview, Design, Validate, Plan, Review, and Develop.

4. Type:

```text
Create a tiny CLI with tests
```

5. Confirm stages stream as readable transcript rows such as `● Interview`, `✓ Design`, tool cards, worker rows, and `✓ Done` or an actionable failure block.

6. Type:

```text
/status
```

7. Confirm status appears as a compact overlay.

8. Type:

```text
/dashboard
```

9. Confirm the old monitoring view appears only now.

10. Type:

```text
/chat
```

11. Confirm transcript mode returns.

12. Type:

```text
@
```

13. Confirm file autocomplete behavior is available in tests and project-root bounded. Current live UI inserts literal `@path` references; structured file refs are not part of the core contract yet.

14. If Pi is absent, trigger a develop-stage run.

15. Confirm missing Pi CLI renders as an actionable error with `/doctor`, `/secrets`, and retry guidance rather than raw dump spam.
