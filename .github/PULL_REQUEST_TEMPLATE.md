## Summary

Describe the user-visible change and why it belongs in this integration.

## Validation

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `mypy custom_components/speedport_smart`
- [ ] `python scripts/check_translations.py`
- [ ] `python scripts/release_metadata.py`
- [ ] `node --check custom_components/speedport_smart/frontend/accessibility.js`
- [ ] `node --check custom_components/speedport_smart/frontend/controls.js`
- [ ] `node --check custom_components/speedport_smart/frontend/entity-state.js`
- [ ] `node --check custom_components/speedport_smart/frontend/speedport-smart-panel.js`
- [ ] `node --check custom_components/speedport_smart/frontend/translations.js`
- [ ] `node --test tests/frontend/*.test.mjs`
- [ ] `pytest`
- [ ] `python scripts/build_release.py`

## Checklist

- [ ] The manifest and `pyproject.toml` versions match for a stable release.
- [ ] User-facing behavior and documentation are updated together.
- [ ] No credentials, router dumps, or private identifiers are included.
- [ ] Router-mutating behavior is explicit, guarded, and documented.
- [ ] Hassfest and HACS validations pass without ignored checks.
