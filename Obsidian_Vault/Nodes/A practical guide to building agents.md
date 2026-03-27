---
id: 532
title: "A practical guide to building agents"
authors: ""
tags: ["manager pattern", "prompt injection", "workflow automation", "accuracy target", "tool overload", "knowledge transfer", "complex tasks", "workflow", "relevance classifier", "API Platform", "moderation", "high-risk actions", "decentralized pattern", "decision-making", "human intervention mechanism", "OpenAI and Safety", "LLMs", "agent orchestration", "evaluation", "PII filter", "building guardrails", "orchestration", "workflow execution", "user input handling", "agent design", "exit condition", "output validation", "ChatGPT Enterprise", "LLM applications", "model selection", "user interaction", "LLM-based deployment", "tool safeguards", "system reliability", "agents", "LLM", "decision making", "AI ethics", "instructions", "complex logic", "single-agent systems", "data privacy", "handoff function", "prompt processing", "refinement", "prompt templates", "guardrails", "security and user experience optimization", "tools", "multi-agent systems", "guardrail tripwire triggered", "complexity management", "large language models", "automation", "model flexibility", "document processing", "orchestration patterns", "friction reduction", "transformation and scalability", "rules-based protections", "failure thresholds", "performance baseline", "content safety", "unstructured data", "OpenAI Stories", "OpenAI for Business", "real-world edge cases", "performance optimization", "safety classifier", "APIs", "guardrail function output", "cost optimization"]
---

# A practical guide to building agents

## Summary (EN)
This guide is designed for product and engineering teams exploring how to build their first agents, distilling insights from numerous customer deployments into practical and actionable best practices. It includes frameworks for identifying promising use cases, clear patterns for designing agent logic and orchestration, and best practices to ensure your agents run safely, predictably, and effectively.

## Relationships
- [[A practical guide to building agents]] --mentionne--> [[agents]]
- [[A practical guide to building agents]] --mentionne--> [[large language models]]
- [[A practical guide to building agents]] --mentionne--> [[LLMs]]
- [[A practical guide to building agents]] --mentionne--> [[workflow execution]]
- [[A practical guide to building agents]] --mentionne--> [[decision making]]
- [[A practical guide to building agents]] --mentionne--> [[complex tasks]]
- [[agent design]] --consists of--> [[three core components]]
- [[LLM]] --powers--> [[reasoning and decision-making]]
- [[tools]] --extend--> [[agents' capabilities]]
- [[instructions]] --define--> [[how the agent behaves]]
- [[tools]] --can be used for--> [[taking action]]
- [[evaluation]] --establishes--> [[performance baseline]]
- [[model selection]] --focuses--> [[on accuracy target]]
- [[optimization]] --targets--> [[cost and latency]]
- [[orchestration patterns]] --include--> [[single-agent systems]]
- [[orchestration patterns]] --include--> [[multi-agent systems]]
- [[exit condition]] --defined by--> [[tool calls or structured output]]
- [[prompt templates]] --reduce--> [[complexity management]]
- [[agent design]] --incorporates--> [[guardrails and hooks]]
- [[model selection]] --considerations--> [[task complexity, latency, cost]]
- [[orchestration patterns]] --enable--> [[workflow execution]]
- [[tools]] --types--> [[data, action, orchestration]]
- [[multi-agent systems]] --mentionne--> [[agent orchestration]]
- [[manager pattern]] --mentionne--> [[orchestration]]
- [[decentralized pattern]] --mentionne--> [[handoff function]]
- [[tool overload]] --mentionne--> [[prompt injection]]
- [[complex logic]] --mentionne--> [[knowledge transfer]]
- [[prompt injection]] --mentionne--> [[user input handling]]
- [[guardrails]] --mentionne--> [[LLM-based deployment]]
- [[LLM-based deployment]] --mentionne--> [[handoff function]]
- [[handoff function]] --mentionne--> [[user input handling]]
- [[user input handling]] --mentionne--> [[transformation and scalability]]
- [[transformation and scalability]] --mentionne--> [[performance optimization]]
- [[knowledge transfer]] --mentionne--> [[prompt processing]]
- [[guardrails]] --include--> [[relevance classifier]]
- [[guardrails]] --include--> [[safety classifier]]
- [[guardrails]] --include--> [[PII filter]]
- [[guardrails]] --include--> [[moderation]]
- [[guardrails]] --include--> [[tool safeguards]]
- [[rules-based protections]] --are--> [[simple deterministic measures]]
- [[output validation]] --ensures--> [[responses align with brand values]]
- [[building guardrails]] --focuses--> [[on data privacy and content safety]]
- [[building guardrails]] --add--> [[new guardrails based on real-world edge cases]]
- [[guardrails]] --optimize--> [[for security and user experience]]
- [[human intervention mechanism]] --triggers--> [[when agent exceeds failure thresholds]]
- [[human intervention mechanism]] --handles--> [[high-risk actions]]
