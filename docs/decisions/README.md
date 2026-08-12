# Architecture Decision Records

The *why* behind every load-bearing choice, distilled from PR bodies and
session decisions so it survives them. ADRs are append-only: a reversed
decision gets a new ADR that names what it supersedes — the record shows what
we believed and when.

Format: Status, Date, Context (the forces), Decision, Consequences (including
the costs — an ADR with no downside listed is marketing), References.

| # | Decision |
|---|---|
| 0001 | The assistant never moves money and never sees an account |
| 0002 | Permissions in code, roles in the database |
| 0003 | Sync SQLAlchemy with psycopg2, not asyncpg |
| 0004 | No vendor SDKs — every external service over plain REST |
| 0005 | Dependency-free BM25 retrieval |
| 0006 | Three-tier answering, in cost order |
| 0007 | Multi-tenancy by bank_id filter, asserted in tests |
| 0008 | Five languages as complete string tables — draft, ship, review |
| 0009 | Prospect tenants carry mandatory disclaimers |
| 0010 | Channel adapters share one conversation core |
| 0011 | The Meta products are one module |
| 0012 | Security controls are mutation-tested |
| 0013 | Docs are tested against code |
| 0014 | SMS is a contract, not an integration |
| 0015 | "Ask OKM" pulls the portal's content; it is never pushed to |
| 0016 | Positioning stays horizontal; Swahili leads the next languages |
| 0017 | Global search reuses existing list views; no new detail screen |
