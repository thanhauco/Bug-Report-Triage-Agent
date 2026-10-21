After upgrading from v2.2 to v2.3 the app crashes immediately on startup.

Steps to reproduce:
1. Install v2.3 with an existing `settings.yaml` from v2.2
2. Run `app serve`

Expected: server starts.
Actual: crash with

```
Traceback (most recent call last):
  File "app/config/loader.py", line 42, in load_config
    timeout = raw["network"]["timeout"]
KeyError: 'network'
```

The v2.2 config has no `network` section. `ConfigLoader` seems to assume it exists.
