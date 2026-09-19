"""Keyword matching that understands tech names.

- Synonyms: K8s = Kubernetes, Postgres = PostgreSQL, JS = JavaScript, ...
- Word boundaries that know tech spellings: `C` doesn't match inside `C++` or
  `C#`, `Java` doesn't match `JavaScript`, and `Node.js` is one word.
- Short spellings (Go, R, TS, ML, AI) only count in that exact casing, so
  "we go to market" isn't Go.
- Tech names that are also everyday words (spark, express, swift, rust, react)
  only count when capitalized, so "spark interest" isn't Spark.
"""

from __future__ import annotations

import re
from functools import lru_cache

# The first spelling in each group is the canonical one.
SYNONYM_GROUPS: list[list[str]] = [
    ["Kubernetes", "K8s", "k8s"],
    ["JavaScript", "JS", "ECMAScript"],
    ["TypeScript", "TS"],
    ["PostgreSQL", "Postgres", "psql"],
    ["MySQL"],
    ["Microsoft SQL Server", "SQL Server", "MSSQL", "MS SQL"],
    ["MongoDB", "Mongo"],
    ["Amazon Web Services", "AWS"],
    ["Google Cloud Platform", "GCP", "Google Cloud"],
    ["Microsoft Azure", "Azure"],
    ["Amazon S3", "S3"],
    ["Amazon EC2", "EC2"],
    ["AWS Lambda", "Lambda"],
    ["Amazon DynamoDB", "DynamoDB"],
    ["Amazon Redshift", "Redshift"],
    ["Machine Learning", "ML"],
    ["Artificial Intelligence", "AI"],
    ["Deep Learning", "DL"],
    ["Natural Language Processing", "NLP"],
    ["Computer Vision"],
    ["Large Language Models", "LLM", "LLMs", "Large Language Model"],
    ["Retrieval-Augmented Generation", "RAG", "Retrieval Augmented Generation"],
    ["Generative AI", "GenAI", "Gen AI"],
    ["CI/CD", "CICD", "CI CD", "Continuous Integration and Continuous Delivery", "Continuous Integration/Continuous Deployment"],
    ["Continuous Integration", "CI"],
    ["Continuous Delivery", "Continuous Deployment", "CD"],
    ["Node.js", "NodeJS", "Node"],
    ["React", "React.js", "ReactJS"],
    ["React Native"],
    ["Vue.js", "Vue", "VueJS"],
    ["Angular", "AngularJS", "Angular.js"],
    ["Next.js", "NextJS"],
    ["Express.js", "Express", "ExpressJS"],
    ["Go", "Golang"],
    ["C#", "CSharp", "C Sharp"],
    ["C++", "CPP"],
    [".NET", "dotnet", "DotNet", ".NET Core", "ASP.NET"],
    ["Objective-C", "ObjC"],
    ["Ruby on Rails", "Rails", "RoR"],
    ["Spring Boot", "SpringBoot"],
    ["Spring"],
    ["REST APIs", "REST API", "RESTful APIs", "RESTful API", "RESTful", "REST"],
    ["GraphQL"],
    ["gRPC"],
    ["WebSockets", "WebSocket"],
    ["Microservices", "Microservice", "Micro-services", "Microservice architecture"],
    ["Distributed Systems", "Distributed System"],
    ["Site Reliability Engineering", "SRE"],
    ["Infrastructure as Code", "IaC"],
    ["Terraform"],
    ["Docker"],
    ["Containerization", "Containers", "Containerized"],
    ["Apache Kafka", "Kafka"],
    ["Apache Spark", "Spark", "PySpark"],
    ["Apache Airflow", "Airflow"],
    ["Apache Flink", "Flink"],
    ["Hadoop", "Apache Hadoop"],
    ["RabbitMQ"],
    ["Redis"],
    ["Elasticsearch", "Elastic Search", "ELK"],
    ["PyTorch", "Torch"],
    ["TensorFlow"],
    ["scikit-learn", "sklearn", "scikit learn"],
    ["pandas"],
    ["NumPy"],
    ["Hugging Face", "HuggingFace"],
    ["Data Structures and Algorithms", "DSA", "Data Structures & Algorithms"],
    ["Object-Oriented Programming", "OOP", "Object Oriented Programming", "Object-Oriented Design", "OOD"],
    ["Test-Driven Development", "TDD", "Test Driven Development"],
    ["Unit Testing", "Unit Tests"],
    ["User Interface", "UI"],
    ["User Experience", "UX"],
    ["UI/UX", "UX/UI"],
    ["HTML", "HTML5"],
    ["CSS", "CSS3"],
    ["Sass", "SCSS"],
    ["Tailwind CSS", "Tailwind", "TailwindCSS"],
    ["OAuth", "OAuth2", "OAuth 2.0"],
    ["JSON Web Tokens", "JWT", "JWTs"],
    ["A/B Testing", "AB Testing", "A/B Tests", "Split Testing"],
    ["ETL", "ELT", "Extract, Transform, Load"],
    ["Data Pipelines", "Data Pipeline"],
    ["Power BI", "PowerBI"],
    ["Microsoft Excel", "Excel", "MS Excel"],
    ["Google Analytics", "GA4"],
    ["GitHub Actions"],
    ["GitLab CI", "GitLab CI/CD"],
    ["Jenkins"],
    ["Linux"],
    ["Unix"],
    ["Bash", "Shell Scripting", "Shell"],
    ["SQL"],
    ["NoSQL"],
    ["Snowflake"],
    ["dbt", "data build tool"],
    ["BigQuery", "Google BigQuery"],
    ["Prometheus"],
    ["Grafana"],
    ["Datadog"],
    ["Observability"],
    ["Monitoring"],
    ["Agile"],
    ["Scrum"],
    ["Jira"],
    ["Figma"],
    ["Selenium"],
    ["Cypress"],
    ["Jest"],
    ["pytest", "PyTest"],
    ["JUnit"],
    ["Flutter"],
    ["Kotlin"],
    ["Swift", "SwiftUI"],
    ["Rust"],
    ["Scala"],
    ["Python", "Python3"],
    ["Java"],
    ["R"],
    ["MATLAB"],
    ["FastAPI"],
    ["Django", "Django REST Framework", "DRF"],
    ["Flask"],
    ["Celery"],
    ["Helm"],
    ["Ansible"],
    ["Git"],
    ["Version Control"],
    ["System Design"],
    ["Caching", "Cache"],
    ["Load Balancing", "Load Balancer", "Load Balancers"],
    ["Message Queues", "Message Queue", "Message Broker", "Message Brokers"],
    ["Serverless"],
    ["Webhooks", "Webhook"],
    ["Stripe"],
    ["Payments", "Payment Systems", "Payment Processing"],
    ["Security", "Application Security", "AppSec"],
    ["Authentication", "AuthN"],
    ["Authorization", "AuthZ"],
]

# Everyday English words that are also tech names: they only count when capitalized.
AMBIGUOUS = {
    "spark", "express", "swift", "rust", "react", "go", "spring", "rails", "shell", "excel",
    "lambda", "jest", "helm", "node", "flask", "airflow", "vault", "hive", "glue", "beam",
    "storm", "chef", "puppet", "unity", "cypress", "jasmine", "mocha", "ember", "backbone",
    "meteor", "elm", "crystal", "julia", "dart", "torch", "cache", "containers",
    "monitoring", "security", "payments", "authentication", "authorization", "shell",
}

_SYN_INDEX: dict[str, int] = {}
for _i, _group in enumerate(SYNONYM_GROUPS):
    for _v in _group:
        _SYN_INDEX.setdefault(_v.lower(), _i)


def normalize(term: str) -> str:
    t = term.strip().strip(".,;:()[]\"'").strip()
    return re.sub(r"\s+", " ", t)


def canonical(term: str) -> str:
    t = normalize(term)
    idx = _SYN_INDEX.get(t.lower())
    if idx is None:
        idx = _SYN_INDEX.get(_singular(t.lower()))
    return SYNONYM_GROUPS[idx][0] if idx is not None else t


def _singular(t: str) -> str:
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("es") and len(t) > 4 and t[-3] in "sxz":
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        return t[:-1]
    return t


def variants(term: str) -> list[str]:
    """All spellings that count as this term."""
    t = normalize(term)
    idx = _SYN_INDEX.get(t.lower())
    if idx is None:
        idx = _SYN_INDEX.get(_singular(t.lower()))
    if idx is None:
        return [t]
    group = SYNONYM_GROUPS[idx]
    return list(dict.fromkeys([t] + group))


def same_term(a: str, b: str) -> bool:
    return canonical(a).lower() == canonical(b).lower() or _singular(normalize(a).lower()) == _singular(normalize(b).lower())


def _is_case_sensitive(v: str) -> bool:
    return len(v) <= 2 or v.lower() in AMBIGUOUS


@lru_cache(maxsize=4096)
def _variant_regex(v: str) -> re.Pattern[str]:
    parts = re.split(r"[\s\-]+", v)
    body = r"[\s\-]*".join(re.escape(p) for p in parts if p) if len(parts) > 1 else re.escape(v)
    plural = r"(?:e?s)?" if v[-1:].isalpha() and len(v) >= 3 else ""
    pattern = r"(?<![A-Za-z0-9_])" + body + plural + r"(?![A-Za-z0-9_+#])"
    if _is_case_sensitive(v):
        if v.lower() in AMBIGUOUS and len(v) > 2:
            # Capitalized or all-caps only: "Spark", "SPARK", not "spark"
            first = re.escape(v[0].upper())
            rest = re.escape(v[1:])
            pattern = r"(?<![A-Za-z0-9_])(?:" + first + rest + "|" + re.escape(v.upper()) + ")" + plural + r"(?![A-Za-z0-9_+#])"
        return re.compile(pattern)
    return re.compile(pattern, re.IGNORECASE)


def find_term(text: str, term: str) -> list[tuple[int, int]]:
    """Non-overlapping spans where the term, or a synonym of it, appears."""
    spans: list[tuple[int, int]] = []
    for v in variants(term):
        if not v:
            continue
        for m in _variant_regex(v).finditer(text):
            spans.append(m.span())
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def count_term(text: str, term: str) -> int:
    return len(find_term(text, term))


def contains_term(text: str, term: str) -> bool:
    return count_term(text, term) > 0


def is_known_tech(word: str) -> bool:
    """A word or phrase that's in the synonym table (a known tech/skill name)."""
    return normalize(word).lower() in _SYN_INDEX or _singular(normalize(word).lower()) in _SYN_INDEX
