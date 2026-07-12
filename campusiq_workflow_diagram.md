---
title: Campus IQ — End-to-End Workflow (5 Layers)
---
flowchart TD

    classDef open stroke-dasharray:5 5,stroke-width:2px;
    classDef store fill:#e8ecff,stroke:#5566aa,color:#222;
    classDef engine fill:#e6f5e6,stroke:#4c994c,color:#222;
    classDef acad fill:#fff4e0,stroke:#cc8800,color:#222;
    classDef data fill:#f5e8ff,stroke:#8844bb,color:#222;
    classDef optional stroke-dasharray:4 3,fill:#fafafa,stroke:#999,color:#444;

    %% ─────────── LAYER 1 · AUTH & ENTRY ───────────
    subgraph L1[" Layer 1 · Auth & Entry "]
        direction TB
        Login["Student logs in"]
        Canvas[("Canvas LMS\n— mocked for MVP")]
        Pull["Python · Canvas pull\nbuild / refresh JSON"]
        Login --> Pull
        Canvas -. "read-only · every login" .-> Pull
    end

    %% ─────────── LAYER 2 · ONBOARDING & PROFILE INPUT ───────────
    subgraph L2[" Layer 2 · Onboarding & Profile Input "]
        direction TB

        subgraph CareerInput[" Career Fields — two entry paths (student chooses) "]
            direction LR
            Manual["Manual entry\ngoals · target roles · interests\nskills · experience · projects · certs"]
            ResumeUp["Resume upload\n— optional"]:::optional
            Parser["Python · resume parser\nextracts fields into same\ncareer schema as manual entry"]
            ResumeUp -. "optional path" .-> Parser
        end

        AcadInput["Academic enrichment fields\nstudent-entered context\nCanvas can't supply"]
        Edit["Edit / Update button\navailable any time post-onboarding\n— re-upload resume OR edit fields manually"]
        Upd["Python · update script\noverwrites changed fields only"]

        Manual --> Upd
        Parser --> Upd
        AcadInput --> Upd
        Edit -. "re-triggers either path" .-> Upd
    end

    %% ─────────── SHARED RECORD ───────────
    JSON["Unified Student JSON\nacademic + career · one record"]
    DB[("Supabase\nsingle source of truth")]
    Pull --> JSON
    Upd --> JSON
    JSON --> DB

    %% ─────────── LAYER 3 · DASHBOARD ───────────
    subgraph L3[" Layer 3 · Student Dashboard — Streamlit (MVP) "]
        direction TB
        Dash["Renders snapshot\nacademic + career in one view"]
        Gate["Completeness gate\nreads by_feature.ready\nbefore any feature fires"]
        Dash --- Gate
    end
    DB --> Dash

    %% ─────────── LAYER 4 · AI ENGINE ───────────
    subgraph L4[" Layer 4 · AI Engine — DeepSeek R1 via OpenRouter "]
        direction TB

        Trig{"Trigger\nfull · single feature · chat"}
        Orch["Orchestrator\nfires career + academic in parallel"]

        subgraph Career[" Career Agents "]
            FIT["FIT\nRole Explorer\n— target roles, interests,\nmajor_intended"]:::engine
            GAP["GAP\nReadiness Check\n— skills, experience,\ncerts, expected_graduation"]:::engine
            SHIFT["SHIFT\nTrend-Aware Guidance\n— target roles, skills,\nAI exposure"]:::engine
        end

        subgraph Academic[" Academic Agents "]
            PROF["Professor Comment\nAnalyzer\n— 3-5 comments/course,\npattern + theme extraction"]:::acad
            EXAM["Exam Gap\nAnalysis\n— examTopicTags,\nscores, loss patterns"]:::acad
            STUDY["Study Guide\nGenerator\n— exam tags, gaps,\ncourse content"]:::acad
            COURSE["Course & Cert\nRecommender\n— GPA, goals,\nTAMU catalog"]:::acad
        end

        Synth["Career Synthesis\nmerges FIT + GAP + SHIFT"]
        Rep["Report Generator\nunified academic + career output"]

        Trig --> Orch
        Orch ==> FIT & GAP & SHIFT
        Orch ==> PROF & EXAM & STUDY & COURSE
        FIT & GAP & SHIFT ==> Synth
        Synth --> Rep
        PROF & EXAM & STUDY & COURSE ==> Rep
    end

    DB --> Orch
    Gate -. "gates feature triggers\non by_feature.ready" .-> Trig

    %% ─────────── CAREER / LABOR-MARKET DATA ───────────
    subgraph DATA[" Career & Labor-Market Data "]
        direction LR
        Web["Live web search\nPRIMARY\n— real-time DFW postings\n+ market signals"]:::data
        Snap[("Supabase snapshot\nFALLBACK / enrichment\n— pre-validated DFW data\n+ O*NET flat files\n+ static industry reports")]:::store
    end

    Web --> FIT & GAP & SHIFT
    Snap --> FIT & GAP & SHIFT

    %% ─────────── ACADEMIC DATA ───────────
    subgraph ADATA[" Academic Data "]
        direction LR
        TAMUCat["TAMU Course Catalog\n— scraped"]:::data
        CertDB["Cert Databases\n— Coursera etc."]:::data
    end

    TAMUCat --> COURSE
    CertDB --> COURSE

    %% ─────────── LAYER 5 · OUTPUT ───────────
    subgraph L5[" Layer 5 · Output "]
        direction TB
        Screen["On-screen results\nper feature or full report"]
        Dl["PDF / DOCX export\nper-feature OR combined report"]
    end
    Rep --> Screen
    Rep --> Dl

    class Canvas,DB,Snap store;