# Architecture — Industry Mentor LLM Agent

> **How to use the diagrams:** they are [Mermaid](https://mermaid.js.org). In **VS Code** (built-in Markdown preview + the *Markdown Preview Mermaid Support* extension) or **Obsidian**, nodes are **clickable** and open the source file. On GitHub, diagrams render but click-links are disabled; use the file table under each diagram instead. Each `▶ Details` block expands to show one component's internals.

---

## 1. System context

```mermaid
flowchart LR
    Mentor([👩‍🏫 Industry Mentor])
    Admin([🛠 Admin / Mentor<br/>maintains standards])
    subgraph Tool["Intelligent Review Assistant (local)"]
        UI[React UI<br/>:5173]
        API[FastAPI backend<br/>:8000]
    end
    LLM[(LLM API<br/>DeepSeek / Qwen / OpenRouter / Groq / OpenAI / Claude / Ollama)]
    VIS[(Vision model API<br/>Qwen-VL / GPT-4o-mini / Claude / Ollama VL)]
    EMB[(Embedding model<br/>API or local bge-zh)]

    Mentor -- upload material, review, edit comments, export --> UI
    Admin -- upload standards, program reqs, exemplars; edit prompts --> UI
    UI -- REST/JSON --> API
    API -- chat completions --> LLM
    API -- embeddings --> EMB
    API -- figure images --> VIS
```

---

## 2. Container / layer view

```mermaid
flowchart TB
    subgraph FE["Frontend · React + Vite + TS"]
        P1[UploadPage]:::fe
        P2[ReviewPage]:::fe
        P3[PromptsPage]:::fe
        P4[KnowledgeBasePage]:::fe
        C1[api/client.ts]:::fe
        P1 & P2 & P3 & P4 --> C1
    end

    subgraph BE["Backend · FastAPI"]
        direction TB
        subgraph API["HTTP layer · app/api/"]
            A1[documents.py]
            A2[reviews.py]
            A3[comments.py]
            A4[prompts.py]
            A5[kb.py]
        end
        subgraph SVC["Domain services · app/"]
            S1[parsing/<br/>parse_file]
            S2[summarize.py<br/>summarize_document]
            S3[runner.py<br/>run_review]
            S4[kb.py<br/>add_source / search]
            S5[prompts.py<br/>render / validate]
            S6[export.py<br/>to_docx / to_markdown]
            S7[figures.py<br/>describe_figures]
        end
        subgraph INFRA["Infrastructure"]
            I1[llm.py<br/>get_chat_model / get_embeddings]
            I2[db.py + models.py<br/>SQLModel]
            I3[config.py<br/>Settings]
        end
    end

    subgraph STORE["Local data · DATA_DIR"]
        D1[(app.db<br/>SQLite)]
        D2[(chroma/<br/>vectors)]
        D3[(uploads/<br/>original files + figures/*.png)]
    end

    EXT[(LLM + Embedding APIs)]

    C1 -->|/api/*| API
    A1 --> S1
    A2 --> S3
    A2 --> S6
    A3 --> I2
    A4 --> S5
    A5 --> S4
    S3 --> S7
    S7 --> I1
    S3 --> S2
    S3 --> S4
    S3 --> S5
    S2 --> S5
    S2 --> I1
    S3 --> I1
    S4 --> I1
    S4 --> S1
    I1 --> EXT
    I2 --> D1
    S4 --> D2
    A1 --> D3

    classDef fe fill:#e8f1ff,stroke:#3b82f6
    click A1 "backend/app/api/documents.py" "Upload / list / get documents"
    click A2 "backend/app/api/reviews.py" "Create review, poll status, export"
    click A3 "backend/app/api/comments.py" "Mentor edits comments"
    click A4 "backend/app/api/prompts.py" "Prompt CRUD"
    click A5 "backend/app/api/kb.py" "Knowledge base CRUD"
    click S1 "backend/app/parsing/__init__.py"
    click S2 "backend/app/summarize.py"
    click S3 "backend/app/review.py"
    click S4 "backend/app/kb.py"
    click S5 "backend/app/prompts.py"
    click S6 "backend/app/export.py"
    click S7 "backend/app/figures.py"
    click I1 "backend/app/llm.py"
    click I2 "backend/app/models.py"
    click I3 "backend/app/config.py"
    click P1 "frontend/src/pages/UploadPage.tsx"
    click P2 "frontend/src/pages/ReviewPage.tsx"
    click P3 "frontend/src/pages/PromptsPage.tsx"
    click P4 "frontend/src/pages/KnowledgeBasePage.tsx"
    click C1 "frontend/src/api/client.ts"
```

| Layer | Rule |
|---|---|
| `app/api/*` | Thin: validate input, call one service, map errors to HTTP. No LLM calls here. |
| Domain services | Pure-ish functions; take a chat model / store as an argument (or default from `llm.py`) so tests inject fakes. |
| `llm.py` | The **only** place that constructs LangChain chat/embedding models. Retries, timeouts, provider switch live here. |
| `prompts.py` | The **only** source of prompt text. Defaults in code, overrides in DB. |

<details>
<summary>▶ Details: <code>parsing/</code> — document parser & sectionizer</summary>

```mermaid
flowchart LR
    F[upload file] --> X{extension}
    X -->|.docx| D[_parse_docx<br/>python-docx: paragraphs, Heading styles, tables]
    X -->|.pdf| P[_parse_pdf<br/>PyMuPDF: blocks + font size + page no.]
    X -->|.txt/.md| T[_parse_text<br/>markdown # or numbered lines]
    X -->|other| E1[[UnsupportedFileType 415]]
    D & P & T --> B[RawBlocks: text, style, level?, page?, image?]
    D -.->|w:drawing, charts, alt text| IMG
    P -.->|raster xrefs + vector clusters| IMG
    IMG[FigureStore.add + attach_captions<br/>filter logos/icons · convert to RGB PNG ≤1600px<br/>attach caption 图/Figure/表 · chart XML → numbers] --> B
    B --> S[build_sections<br/>1. heading styles<br/>2. numbering regex 1 / 1.1 / 一、/ 第X章<br/>3. fallback: chunk ~800 chars into pseudo-sections]
    S --> V{any text?}
    V -->|no| E2[[EmptyDocument / ScannedPdf 422]]
    V -->|yes| O[ParsedDocument<br/>sections S1..Sn, paragraphs S1.P1..<br/>figures = paragraphs kind=figure]
```
</details>

<details>
<summary>▶ Details: <code>summarize.py</code> — structured summary</summary>

```mermaid
flowchart LR
    D[ParsedDocument] --> T{tokens ≤ 60% of<br/>LLM_CONTEXT_TOKENS?}
    T -->|yes: stuff| S1[one call: prompt summary_reduce<br/>with full text]
    T -->|no: map-reduce| M[map: per section<br/>prompt summary_map → text notes]
    M --> R[reduce: prompt summary_reduce<br/>over all notes]
    S1 & R --> SO[with_structured_output → StructuredSummary]
    SO --> V[validate source_ids ⊂ doc paragraph IDs<br/>drop unknown IDs]
```
</details>

<details>
<summary>▶ Details: <code>review.py</code> — RAG review engine (features 2 + 3)</summary>

```mermaid
flowchart TB
    Start[run_review review_id] --> Fig[describe_figures — vision model<br/>cached per image · skipped if VISION_MODEL empty<br/>description merged into figure paragraph text]
    Fig --> Sum[summarize_document]
    Sum --> FC[checks.format_checks — rule-based, no LLM<br/>heading numbering gaps · missing references section<br/>figure/table captions · empty sections · length limits]
    FC --> Loop{for each section}
    Loop --> Q[build query = heading + first 500 chars]
    Q --> KB[kb.search query, k per category, filter doc_type]
    KB --> Ctx[context = standards + program reqs + exemplar excerpts]
    Ctx --> LLMc[review_section → prompt section_review<br/>with_structured_output → SectionReview]
    LLMc -->|invalid / timeout| Retry{retries left?}
    Retry -->|yes| LLMc
    Retry -->|no| Fail[mark section failed, continue]
    LLMc --> Anc[anchor_comments<br/>• paragraph_id exists?<br/>• quote ⊂ paragraph? else fuzzy ≥ 0.85<br/>• else relocate by quote across doc<br/>• else section-level, anchored=false]
    Anc --> Dedup[dedupe similar comments]
    Dedup --> Save[(save ReviewComments)]
    Fail --> Loop
    Save --> Loop
    Loop -->|done| Status[status = done or partial]
```
</details>

<details>
<summary>▶ Details: <code>kb.py</code> — knowledge base</summary>

```mermaid
flowchart LR
    U[upload source<br/>category + doc_type] --> H{sha256 already<br/>in KBSource?}
    H -->|yes| Dup[[409 duplicate]]
    H -->|no| P[parsing.parse_file]
    P --> Sp[RecursiveCharacterTextSplitter<br/>chunk 800 / overlap 100<br/>Chinese-aware separators]
    Sp --> E[embeddings]
    E --> C[(Chroma collection 'kb'<br/>metadata: source_id, category, doc_type, chunk_id)]
    Q[search query, category, doc_type, k] --> C
    C --> R[list KBHit text, source, score]
```
</details>

---

## 3. Data model

```mermaid
erDiagram
    DOCUMENT ||--o{ REVIEW : "reviewed by"
    REVIEW ||--o{ REVIEW_COMMENT : contains
    FIGURE_CACHE }o--o{ DOCUMENT : "describes figures of"
    PROMPT_TEMPLATE ||--o{ PROMPT_VERSION : versions
    KB_SOURCE ||--o{ KB_CHUNK : "chunked into (in Chroma)"

    DOCUMENT {
        int id PK
        string filename
        string sha256
        string doc_type "report|proposal|technical"
        string language "zh|en"
        json parsed "ParsedDocument: sections, paragraphs"
        json warnings
        datetime created_at
    }
    REVIEW {
        int id PK
        int document_id FK
        string status "queued|running|done|partial|failed"
        string stage "figures|summary|format|sections k/n|done"
        json summary "StructuredSummary (null until the summary step)"
        json warnings
        int figures_analysed
        string overall_feedback "mentor-editable"
        json prompt_versions "key → version used"
        string model
        json errors
        datetime started_at
        datetime finished_at
    }
    FIGURE_CACHE {
        string key PK "image sha256[:32] : figure_describe prompt version"
        json data "FigureDescription"
    }
    REVIEW_COMMENT {
        int id PK
        int review_id FK
        string section_id "S3"
        string paragraph_id "S3.P2 or null"
        string quote
        bool anchored
        string category "evidence|feasibility|logic|format|completeness|clarity|innovation|citation"
        string severity "high|medium|low"
        string problem
        string suggestion
        json revision_steps
        json standard_refs
        string origin "ai|rule|mentor"
        string status "pending|accepted|edited|rejected"
        string mentor_text
    }
    PROMPT_TEMPLATE {
        string key PK "summary_map|summary_reduce|section_review|overall_feedback|figure_describe"
        int active_version
    }
    PROMPT_VERSION {
        int id PK
        string key FK
        int version
        string system_text
        string user_text
        datetime created_at
    }
    KB_SOURCE {
        int id PK
        string filename
        string sha256
        string category "standard|program_requirement|exemplar"
        string doc_type "report|proposal|technical|any"
        int chunk_count
        string embedding_model "mismatch with EMBEDDING_MODEL → re-index"
    }
    KB_CHUNK {
        string chunk_id PK
        int source_id
        string text
        vector embedding
    }
```

`ParsedDocument` is stored as JSON in `DOCUMENT.parsed` — it's read whole and never queried by field, so a table per paragraph would be overhead.

---

## 4. Review lifecycle (state machine)

```mermaid
stateDiagram-v2
    [*] --> queued: POST /api/reviews
    queued --> running: background task starts
    running --> done: all figures + sections reviewed
    running --> partial: ≥1 section failed, others ok
    running --> failed: summary failed / LLM unreachable / all sections failed
    failed --> queued: POST /api/reviews/{id}/retry
    partial --> queued: retry failed sections only
    done --> [*]
    note right of running
        stage field shows progress:
        figures k/n → summary → format → section k/n
    end note
```

Comment lifecycle (mentor side):

```mermaid
stateDiagram-v2
    [*] --> pending: created by AI or rule
    [*] --> accepted: mentor adds own comment (origin=mentor)
    pending --> accepted: confirm ✔
    pending --> edited: adjust ✎
    pending --> rejected: reject ✖
    edited --> edited
    rejected --> pending: undo
    accepted --> pending: undo
    note right of accepted
        export includes accepted + edited only
    end note
```

---

## 5. REST API

| Method | Path | Purpose | Main errors |
|---|---|---|---|
| POST | `/api/documents` | multipart upload → parse → store | 413 too large · 415 type · 422 empty/scanned/encrypted |
| GET | `/api/documents` · `/api/documents/{id}` | list / get with parsed sections | 404 |
| DELETE | `/api/documents/{id}` | delete doc + reviews + figure files | 404 |
| GET | `/api/documents/{id}/figures/{image_id}` | figure PNG for the viewer | 404 |
| POST | `/api/reviews` `{document_id}` | create review, start background run | 404 doc · 503 LLM not configured |
| GET | `/api/reviews/{id}` | status, stage, summary, comments | 404 |
| POST | `/api/reviews/{id}/retry` | re-run failed parts | 409 if running |
| GET | `/api/reviews/{id}/export?format=docx\|md` | final feedback file (accepted + edited + mentor comments) | 409 while running · 422 bad format |
| POST · PUT | `/api/reviews/{id}/overall` | generate overall feedback from confirmed comments · save mentor's text | 409 none confirmed / running · 502 LLM failed |
| PATCH | `/api/comments/{id}` | status / mentor_text / severity / category | 404 · 422 (`EMPTY_EDIT`) |
| POST | `/api/reviews/{id}/comments` | mentor adds comment (paragraph, section or whole document) | 422 `BAD_ANCHOR` · `BAD_QUOTE` |
| POST | `/api/reviews/{id}/comments/bulk` `{ids, status}` | e.g. accept all high-severity | 422 `UNKNOWN_COMMENTS` |
| DELETE | `/api/comments/{id}` | delete a mentor comment | 403 for AI/rule comments (reject instead) |
| GET | `/api/prompts` · PUT `/api/prompts/{key}` · POST `/api/prompts/{key}/reset` | prompt management | 422 invalid template |
| GET | `/api/prompts/{key}/versions` | history | |
| POST/GET/DELETE | `/api/kb/sources` | knowledge base | 409 duplicate · 415 · 422 |
| GET | `/api/kb/search?q=&category=` | debug: test retrieval | |
| GET | `/api/health` | liveness + LLM configured? | |

---

## 6. Cross-cutting concerns

| Concern | Decision |
|---|---|
| **Long-running work** | FastAPI `BackgroundTasks`; UI polls `GET /api/reviews/{id}` every 2 s. `# ponytail: in-process tasks die with the server; move to a job queue if multi-user.` On startup, reviews stuck in `running` are marked `failed` ("server restarted"). |
| **Concurrency** | Sections reviewed with bounded concurrency (`asyncio.Semaphore(3)`) to respect rate limits. |
| **Providers** | `llm.py` builds everything: OpenAI-compatible client for `openai_compatible`/`openrouter`/`groq` (preset URLs), `ChatAnthropic` for `anthropic`. Vision model reuses the LLM connection unless `VISION_*` overrides it. |
| **LLM failures** | `max_retries` + timeout in `llm.py`; structured-output parse errors retried once with the error appended; then section marked failed. |
| **Prompt injection** | Student text in `<document>` tags; system prompt says content inside is data. Output schema enforced in code. |
| **Images** | Extracted at parse time (no LLM), described at review time by a separate vision model; unsupported formats kept with `analysable=false` so nothing disappears silently. |
| **Hallucinated anchors** | `anchor_comments` validates every ID/quote against the parsed doc. |
| **Hallucinated summary** | `not_found` flag per field; `source_ids` validated. |
| **Reproducibility** | Each review stores the prompt version + model used. |
| **Language** | `OUTPUT_LANGUAGE=auto` → detect from doc (CJK ratio) → `{language}` variable in every prompt. |
| **Security** | Uploads stored under random UUID names (no path traversal), size-limited, extension + magic-byte checked. API binds to `127.0.0.1` by default. CORS limited to the Vite origin. |
| **Privacy** | Student material is sent to the configured LLM provider; README notes this; Ollama option for fully local use. |
