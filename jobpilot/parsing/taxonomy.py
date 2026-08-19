"""Canonical skill/domain vocabulary plus alias resolution.

Job descriptions and your profile never use the same words for the same thing
("PyTorch", "torch", "pytorch lightning"). Everything in JobPilot is normalised
through this module so the matcher compares like with like.

`SKILLS` maps a canonical key to (printable label, category, aliases).
Aliases are matched case-insensitively on word boundaries.
"""

from __future__ import annotations

import re
from functools import lru_cache

# category is used for grouping on the tailored resume
SKILLS: dict[str, tuple[str, str, list[str]]] = {
    # --- languages -------------------------------------------------------
    "python": ("Python", "language", ["python3", "py"]),
    "cpp": ("C++", "language", ["c++", "cpp"]),
    "c": ("C", "language", []),
    "java": ("Java", "language", []),
    "javascript": ("JavaScript", "language", ["js", "node", "nodejs", "node.js"]),
    "typescript": ("TypeScript", "language", ["ts"]),
    "sql": ("SQL", "language", ["postgres", "postgresql", "mysql", "sqlite"]),
    "bash": ("Bash", "language", ["shell scripting", "shell"]),
    "go": ("Go", "language", ["golang"]),
    "rust": ("Rust", "language", []),
    # --- ml frameworks ---------------------------------------------------
    "pytorch": ("PyTorch", "ml_framework", ["torch", "pytorch lightning", "lightning"]),
    "tensorflow": ("TensorFlow", "ml_framework", ["tf", "keras"]),
    "jax": ("JAX", "ml_framework", ["flax"]),
    "huggingface": ("Hugging Face", "ml_framework",
                    ["hugging face", "transformers library", "hf", "peft", "trl", "accelerate"]),
    "sklearn": ("scikit-learn", "ml_framework", ["scikit learn", "sklearn"]),
    "onnx": ("ONNX", "ml_framework", ["onnxruntime", "tensorrt"]),
    "opencv": ("OpenCV", "ml_framework", ["cv2"]),
    "numpy": ("NumPy", "ml_framework", ["numpy", "scipy"]),
    "pandas": ("pandas", "ml_framework", ["dataframes"]),
    # --- ml / ai concepts ------------------------------------------------
    "ml": ("Machine Learning", "ml", ["machine learning", "ml algorithms", "statistical learning"]),
    "deep_learning": ("Deep Learning", "ml", ["deep learning", "neural networks", "dnn"]),
    "nlp": ("NLP", "ml", ["natural language processing", "text processing", "language technology"]),
    "llm": ("LLMs", "ml",
            ["large language model", "large language models", "llms", "gpt", "foundation model",
             "foundational model", "foundation models", "language models"]),
    "llm_finetuning": ("LLM Fine-tuning", "ml",
                       ["fine-tuning", "finetuning", "fine tuning", "lora", "qlora",
                        "sft", "instruction tuning", "post-training", "rlhf", "dpo"]),
    "rag": ("RAG", "ml",
            ["retrieval augmented generation", "retrieval-augmented generation", "rag pipelines",
             "vector search", "vector database", "embeddings search", "semantic search"]),
    "agents": ("LLM Agents", "ml",
               ["agentic", "ai agents", "agent frameworks", "tool use", "langgraph", "langchain",
                "llamaindex", "mcp"]),
    "prompting": ("Prompt Engineering", "ml", ["prompt engineering", "prompting"]),
    "evaluation": ("Model Evaluation", "ml",
                   ["evals", "evaluation", "benchmarking", "benchmarks", "llm evaluation",
                    "model evaluation", "eval harness", "benchmark design", "comet", "bleu",
                    "flores", "flores-200", "wer", "cer", "human-in-the-loop evaluation",
                    "failure mode analysis", "failure-mode analysis"]),
    "cv": ("Computer Vision", "ml",
           ["computer vision", "image processing", "visual recognition", "object detection",
            "image classification", "segmentation"]),
    "ocr": ("OCR", "ml",
            ["optical character recognition", "text recognition", "handwriting recognition",
             "htr", "scene text", "document ai", "document understanding", "document parsing",
             "layout analysis"]),
    "speech": ("Speech / ASR", "ml",
               ["speech recognition", "asr", "tts", "text to speech", "text-to-speech",
                "speech synthesis", "audio ml", "voice ai", "whisper"]),
    "multimodal": ("Multimodal ML", "ml", ["multi-modal", "multimodal", "vision language", "vlm"]),
    "recsys": ("Recommender Systems", "ml", ["recommendation systems", "recommender", "ranking systems"]),
    "timeseries": ("Time Series", "ml", ["time-series", "forecasting"]),
    "rl": ("Reinforcement Learning", "ml", ["reinforcement learning", "rlhf basics", "policy gradient"]),
    "data_engineering": ("Data Engineering", "ml",
                         ["data pipelines", "etl", "data curation", "dataset creation",
                          "data annotation", "corpus building", "web scraping", "data cleaning",
                          "synthetic data generation", "synthetic data", "dataset engineering",
                          "data preprocessing", "deduplication"]),
    "cuda": ("CUDA", "ml_framework", ["cuda", "gpu programming", "gpu kernels"]),
    "mlops": ("MLOps", "ml",
              ["mlops", "model deployment", "model serving", "inference optimization",
               "experiment tracking", "mlflow", "wandb", "weights & biases", "vllm", "triton"]),
    "distributed_training": ("Distributed Training", "ml",
                             ["multi-gpu", "distributed training", "deepspeed", "fsdp",
                              "model parallel", "gpu clusters"]),
    "low_resource_nlp": ("Low-resource NLP", "ml",
                         ["low resource languages", "low-resource", "indic nlp", "indian languages",
                          "multilingual nlp", "regional languages", "under-resourced languages"]),
    "mt": ("Machine Translation", "ml",
           ["machine translation", "neural machine translation", "nmt", "translation systems",
            "seq2seq", "sequence to sequence", "sequence-to-sequence"]),
    # --- software / infra ------------------------------------------------
    "backend": ("Backend Engineering", "software",
                ["backend", "server side", "microservices", "rest api", "restful", "apis",
                 "fastapi", "flask", "django", "grpc", "websocket", "websockets",
                 "real-time systems", "realtime", "supabase"]),
    "frontend": ("Frontend", "software",
                 ["react", "next.js", "nextjs", "vue", "html/css", "ui development",
                  "front-end", "responsive design", "vite"]),
    "git": ("Git", "software", ["github", "version control", "gitlab"]),
    "docker": ("Docker", "software", ["containers", "containerisation", "containerization"]),
    "kubernetes": ("Kubernetes", "software", ["k8s", "eks", "gke"]),
    "aws": ("AWS", "software", ["amazon web services", "ec2", "s3", "sagemaker"]),
    "gcp": ("GCP", "software", ["google cloud", "vertex ai"]),
    "azure": ("Azure", "software", ["microsoft azure"]),
    "linux": ("Linux", "software", ["unix", "ubuntu"]),
    "testing": ("Testing", "software", ["unit tests", "pytest", "test coverage"]),
    "system_design": ("System Design", "software", ["distributed systems", "scalable systems", "architecture"]),
    "cicd": ("CI/CD", "software", ["ci/cd", "github actions", "jenkins", "continuous integration"]),
    # --- research / soft -------------------------------------------------
    "research": ("Research", "research",
                 ["research experience", "publications", "papers", "arxiv", "research engineer",
                  "novel methods", "state of the art", "state-of-the-art"]),
    "writing": ("Technical Writing", "research", ["documentation", "technical writing", "blogging"]),
    "communication": ("Communication", "soft", ["communication skills", "stakeholder management"]),
    "ownership": ("Ownership", "soft", ["ownership", "self-driven", "self driven", "autonomy", "0 to 1", "0-to-1"]),
}

# Problem domains. Used for "does this company work on what I work on".
DOMAINS: dict[str, tuple[str, list[str]]] = {
    "indian_language_ai": ("Indian-language AI",
                           ["indic", "indian languages", "bharat", "hindi", "kashmiri", "tamil",
                            "telugu", "bengali", "marathi", "regional language", "sovereign ai",
                            "multilingual india"]),
    "low_resource_nlp": ("Low-resource NLP",
                         ["low-resource", "low resource", "under-resourced", "endangered language",
                          "language preservation"]),
    "document_ai": ("Document AI / OCR",
                    ["ocr", "document ai", "document understanding", "handwriting", "manuscripts",
                     "digitisation", "digitization", "idp", "intelligent document processing"]),
    "speech_ai": ("Speech AI", ["asr", "tts", "voice", "speech", "conversational voice"]),
    "foundation_models": ("Foundation models",
                          ["foundation model", "foundational model", "pretraining", "pre-training",
                           "frontier model", "sovereign model", "llm training"]),
    "agentic_ai": ("Agentic AI", ["ai agents", "agentic", "autonomous agents", "copilot", "assistant"]),
    "ai_infra": ("AI infrastructure",
                 ["inference", "gpu", "serving", "training infrastructure", "ml platform", "compute"]),
    "computer_vision": ("Computer vision", ["vision", "imaging", "video understanding", "detection"]),
    "healthcare_ai": ("Healthcare AI", ["clinical", "medical imaging", "healthtech", "diagnostics"]),
    "fintech_ai": ("Fintech AI", ["fintech", "payments", "credit risk", "fraud detection"]),
    "robotics": ("Robotics", ["robotics", "drones", "autonomous vehicles", "slam"]),
    "devtools": ("Developer tools", ["developer tools", "devtools", "sdk", "ide", "code generation"]),
    "education_ai": ("Education AI", ["edtech", "learning platform", "tutoring"]),
    "legal_ai": ("Legal AI", ["legal tech", "contracts", "compliance ai"]),
    "search": ("Search & retrieval", ["search engine", "information retrieval", "ranking"]),
}

# Roles we care about, used to filter noisy job feeds.
ROLE_KEYWORDS = [
    "ai engineer", "ml engineer", "machine learning engineer", "applied scientist",
    "research engineer", "research scientist", "llm engineer", "nlp engineer",
    "computer vision engineer", "deep learning engineer", "data scientist",
    "software engineer", "backend engineer", "python developer", "full stack",
    "ai intern", "ml intern", "research intern", "ai researcher", "member of technical staff",
    "mts", "founding engineer", "ai developer", "gen ai", "generative ai", "speech engineer",
    "data engineer", "ai scientist", "prompt engineer", "sde",
]

# checked in order - the first match wins, so the strongest signals come first
_SENIORITY = [
    ("intern", ["intern", "internship", "trainee", "apprentice"]),
    ("senior", ["senior", "sr.", "staff", "principal", "lead", "head of", "manager", "director",
                "architect", "vp "]),
    ("mid", ["mid-level", "engineer ii", "engineer 2", "sde 2", "sde-2"]),
    ("entry", ["fresher", "graduate", "junior", "entry level", "entry-level", "associate"]),
]


def _compile(aliases: list[str]) -> re.Pattern[str]:
    """Word-boundary alternation over aliases.

    Terms of four characters or more also match their plural, so "foundational
    models" hits "foundational model". Short terms do not, otherwise "C" would
    happily match the "CS" in "B.Tech in CS".
    """
    escaped = {re.escape(a) for a in aliases if a}
    longs = sorted((a for a in escaped if len(a) >= 4), key=len, reverse=True)
    shorts = sorted((a for a in escaped if len(a) < 4), key=len, reverse=True)
    parts = []
    if longs:
        parts.append("(?:" + "|".join(longs) + ")s?")
    if shorts:
        parts.append("(?:" + "|".join(shorts) + ")")
    return re.compile(r"(?<![\w+#.])(?:" + "|".join(parts) + r")(?![\w+#])", re.IGNORECASE)


@lru_cache(maxsize=1)
def _skill_patterns() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for key, (label, _cat, aliases) in SKILLS.items():
        terms = [label, key.replace("_", " ")] + list(aliases)
        out.append((key, _compile(terms)))
    return out


@lru_cache(maxsize=1)
def _domain_patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [(key, _compile([label, key.replace("_", " ")] + list(aliases)))
            for key, (label, aliases) in DOMAINS.items()]


def label_of(key: str) -> str:
    if key in SKILLS:
        return SKILLS[key][0]
    if key in DOMAINS:
        return DOMAINS[key][0]
    return key.replace("_", " ").title()


def category_of(key: str) -> str:
    return SKILLS[key][1] if key in SKILLS else "other"


def canonical_skill(text: str) -> str | None:
    """Resolve a free-text skill name (from your profile or a JD bullet)."""
    t = (text or "").strip().lower().replace("-", " ")
    if not t:
        return None
    if t in SKILLS:
        return t
    squashed = t.replace(" ", "_")
    if squashed in SKILLS:
        return squashed
    for key, pattern in _skill_patterns():
        if pattern.fullmatch(t) or pattern.search(t):
            return key
    return None


def extract_skills(text: str) -> dict[str, int]:
    """Canonical skill -> number of mentions in `text`."""
    found: dict[str, int] = {}
    if not text:
        return found
    for key, pattern in _skill_patterns():
        hits = len(pattern.findall(text))
        if hits:
            found[key] = hits
    return found


def extract_domains(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    if not text:
        return found
    for key, pattern in _domain_patterns():
        hits = len(pattern.findall(text))
        if hits:
            found[key] = hits
    return found


def canonical_domain(text: str) -> str | None:
    t = (text or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in DOMAINS:
        return t
    hits = extract_domains(text)
    return max(hits, key=hits.get) if hits else None


def seniority_of(title: str) -> str:
    t = f" {(title or '').lower()} "
    for name, markers in _SENIORITY:
        if any(m in t for m in markers):
            return name
    return "unspecified"


def looks_like_target_role(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in ROLE_KEYWORDS)
