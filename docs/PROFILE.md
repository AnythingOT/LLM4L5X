# Company coding-standards profile

A YAML file with the rules that differ per company. Checked by `cli.py validate FILE --profile std.yaml`
and by `lint.run(..., profile=)` / `lint.check_rungs(..., profile=)`.

```yaml
name: Example Co.
naming:                       # data type -> pattern the tag name must match; "any" = every tag
  TIMER: '_(TMR|TON|TOF)$'
  COUNTER: '_CTR$'
  any: '^[A-Z]'
banned_instructions: [JMP, LBL]
restricted:                   # instruction -> pattern its first operand must match
  OTL: '_(ALM|Fail)$'         # latches only for alarms and faults
rung_comments: required
disabled_rules: [INF004]      # built-in rules this company does not use
```

| code | severity | fires when |
|---|---|---|
| STD001 | warning | a tag name does not match its data type's pattern (or `any`) |
| STD002 | error | a banned instruction is used |
| STD003 | error | a restricted instruction's first operand does not match its pattern |
| STD004 | warning | a rung has no comment and `rung_comments: required` |

- A project export is checked on the tags it **defines**; generated rungs on the tags they **use**.
  Module tags (`Local:1:I.Data`) are named by Logix and skipped.
- A profile adds rules and switches rules off. It **cannot change a severity**: a code means the same
  thing in every report, whichever company ran it.
- `lint:disable=STD003` in a rung comment or tag description accepts one case, as for any rule.
- Keep a company profile outside this repo, like a company block library.
