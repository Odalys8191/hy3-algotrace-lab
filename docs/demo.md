# Two-minute demo checklist

`scripts/demo.sh` can drive one local API run but does **not** record a video/GIF and makes no
claim that a recording exists. Use it only after the integrated Task 5 API, Task 6 Streamlit
client, verified formal catalog, pinned Docker Judge, and authorised local environment are
available.

1. Run `python -m hy3_algotrace.release_validation --root .` and start localhost-only Compose.
2. Select one verified public problem; do not reveal protected tests/oracle/reference code.
3. Show Streamlit making HTTP requests only and FastAPI accepting the run with `202`.
4. Run `HY3_DEMO_PROBLEM_ID=<verified-id> scripts/demo.sh`; it permits only an exact
   `http://127.0.0.1:<port>` URL, polls to `completed`/`failed`, and prints a safe public report
   or first failure rather than assuming success.
5. Show the public trace/Judge summary, first material error and `needs_human_review` where
   applicable, then the immutable run ID/hash.
6. End with `个人活动实战作品，非腾讯官方发布` and state any missing formal gate.

The URL check rejects TLS, `localhost`, paths, queries, fragments, implicit ports, and userinfo
forms such as an untrusted authority before `@127.0.0.1`. Never place credentials in a demo
command, screen recording, shell history, artifact, or issue.
