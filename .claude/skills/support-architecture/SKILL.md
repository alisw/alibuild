---
name: support-architecture
description: Use this skill when the user asks to add support for a new Linux distribution or architecture flavour (e.g. "add support for rhel10 as slc10", "add ubuntu 24.04", "add rocky 10"). Guides through the two required changes: detection logic in utilities.py and test fixtures in test_utilities.py.
version: 0.1.0
---

# Adding Support for a New Architecture Flavour in alibuild

Architecture detection lives in two files:

- **`alibuild_helpers/utilities.py`** — the `doDetectArch()` function
- **`tests/test_utilities.py`** — fixtures and `architecturePayloads` test table

## Step 1 — Understand how detection works

`doDetectArch()` receives:
- `hasOsRelease` — whether `/etc/os-release` was readable
- `osReleaseLines` — lines of `/etc/os-release`
- `platformTuple` — `(name, version, codename)` from `distro.linux_distribution()`
- `platformSystem`, `platformProcessor`

The function:
1. If `platformTuple`'s distribution is already in a known list → uses it directly.
2. Otherwise falls back to `/etc/os-release`, reading `ID` → `distribution` and `VERSION_ID` → `version`.
3. Applies any distro-name remapping (e.g. mapping a distro name to another prefix).
4. Returns `"{distro}{major_version}_{arch}"` e.g. `slc10_x86-64`.

## Step 2 — Edit `alibuild_helpers/utilities.py`

Look at the `doDetectArch` function and follow the existing pattern for the family the new distro belongs to.

- If the new distro is identified via `/etc/os-release` `ID` field (i.e. `distro.linux_distribution()` doesn't return it directly), add its `ID` value to the appropriate `elif` branch that maps distro names to the desired prefix.
- If the distro needs its own new remapping rule, add a new `elif` branch following the same structure as the existing ones.

Only change what is necessary — if the distro's `NAME` (from `distro.linux_distribution()`) already appears in an existing branch, no change is needed in `utilities.py`.

## Step 3 — Add a fixture in `tests/test_utilities.py`

Add a constant with the contents of the new distro's `/etc/os-release`. Follow the format of the existing fixtures (e.g. `ALMA_9_OS_RELEASE`, `ROCKY_9_OS_RELEASE`). The two fields that matter for detection are **`ID`** and **`VERSION_ID`**:

```python
NEW_DISTRO_OS_RELEASE = """
NAME="Distro Name"
VERSION="10.0 (Codename)"
ID="distro-id"
VERSION_ID="10.0"
...
"""
```

## Step 4 — Add a row to `architecturePayloads`

Each row is:
```python
[expected_arch, hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor]
```

Add one entry per distro variant being tested:

```python
['prefix10_x86-64', True, NEW_DISTRO_OS_RELEASE.split("\n"), ('Distro Name', '10.0', 'Codename'), 'Linux', 'x86_64'],
```

- `expected_arch` — the string `doDetectArch` should return
- `hasOsRelease=True` — os-release is available
- `osReleaseLines` — the fixture split into lines
- `platformTuple` — what `distro.linux_distribution()` returns for this distro
- `platformSystem` — `'Linux'`
- `platformProcessor` — use `'x86_64'` (the function converts underscores to hyphens)

## Checklist

- [ ] `utilities.py` updated if the distro's name/ID is not already handled
- [ ] `/etc/os-release` fixture constant added in `test_utilities.py`
- [ ] Row(s) added to `architecturePayloads` in `test_utilities.py`
- [ ] Tests pass (`tox` or CI)
