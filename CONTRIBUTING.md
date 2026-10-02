# Contributing

Issues and pull requests are welcome. Measurements from other printers and materials are very useful, so if you print the coupons please report what fitted, with the printer, nozzle, material and layer height.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test,sim]'
.venv/bin/pytest
```

Please add a test for every change in behaviour. If a card does not come apart, please attach the parts (or small parts that show the same problem) and the output of `best_card(verbose=True)`.
