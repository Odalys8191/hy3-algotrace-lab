# Two-minute demo checklist

`scripts/demo.sh` is a repeatable local checklist driver; it does **not** record video or GIF
and does not claim that a recording exists. Record only after the integrated Task 5 API, Task
6 UI, verified local Docker Judge, and non-secret local environment are available.

1. Start the integrated localhost-only API and Streamlit UI. Do not expose their ports.
2. Select one verified built-in problem with public statement/examples only.
3. Launch one solve-and-audit run and show the queued-to-terminal status transition.
4. Show the structured trace, generated C++17 source, public Judge summary, first material
   error (if any), taxonomy, and `needs_human_review` indication.
5. Do not display API keys, hidden/generated tests, oracle facts, reference solution source,
   local absolute paths, reviewer-only evidence, or raw internal artifacts.
6. End by showing the immutable run ID/artifact hash and this disclaimer:
   `个人活动实战作品，非腾讯官方发布`.

For a local API smoke sequence after integration:

```sh
HY3_DEMO_PROBLEM_ID=cf-EXAMPLE-a HY3_DEMO_API_BASE_URL=http://127.0.0.1:8000 \
  scripts/demo.sh
```

This example identifier is deliberately not a claim that a formal problem bundle is present.
