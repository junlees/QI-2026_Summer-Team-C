# PRD (Product Requirements Document) — AgriSage

> Agriculture + Sage. "We don't just name the problem. We walk you through it."

**Date**: July 2026
**Team**: Team C — Hyunjun Lee, Hanmin Bae, Minseong Hong, Najin Son, Sehyeon Kim
**Document Status**: Draft v1 (updated after the first presentation)

---

## 1. Overview

AgriSage is an AI-powered agricultural support service that diagnoses crop diseases from a single photo, explains the reasoning behind the diagnosis, recommends a treatment suited to the user's situation, and follows up after treatment to confirm recovery. While existing services stop at "providing diagnostic information," AgriSage aims to complete the entire journey — from diagnosis to post-treatment follow-up — as a single, continuous flow.

---

## 2. Problem Statement

### 2.1 Background
- In 2025, the number of people returning to farming increased by 8.5% year-over-year, but among those who had moved back to rural areas, 73.8% decided to move back to the city again within 3 years of settling — the early settlement period is the most vulnerable stage.
- In online plant consultation data, 79% of inquiries were not actual pests or diseases but issues related to cultivation management or physiological disorders — beginners struggle even to judge whether something is a disease in the first place.
- Pesticide misuse is common not only among beginners but also among experienced farmers (use on unregistered crops, incorrect spray intervals, excessive concentration, etc.) — in an investigation by the National Agricultural Products Quality Management Service, 777 out of roughly 44,000 cases exceeded the standard limit.
- Failure to comply with the international Positive List System (PLS) means the uniform residue limit (0.01ppm) applies by default, which can result in the entire harvest being subject to disposal.

### 2.2 Core Problem (Two-Stage Problem)
| Stage | Problem |
|---|---|
| Stage 1: Diagnosis | Users cannot tell on their own whether it's a disease, overwatering, or a nutrient deficiency |
| Stage 2: Treatment | Even with a correct diagnosis, there is no clear standard for which product to use, how, or when |

---

## 3. Goals

### 3.1 Product Goals
- Provide a reliable first-pass diagnosis from a single photo
- Explain the diagnostic reasoning in language the user can understand
- Recommend treatment products tailored to the user's situation (farming purpose, organic status, etc.)
- Prevent user error through automatic safety standard (PLS) checks
- Provide a closed loop that confirms the outcome after treatment

### 3.2 Success Metrics (proposed, to be refined further)
- Model classification performance (Accuracy, F1 Score)
- User comprehension/satisfaction with diagnostic results (survey-based)
- Return-visit rate after treatment (usage rate of the follow-up feature)
- Rate at which safety-standard warnings are actually shown and recognized by users

---

## 4. Target Users

| Segment | Description |
|---|---|
| Primary | First-3-year growers who recently returned to farming — they have not yet built up basic agricultural judgment, and every decision feels high-stakes |
| Secondary | Small-scale and hobby growers — kitchen gardens, weekend farms, balcony growers; smaller in scale but facing the same uncertainty |

**Shared need**: Confidence in "what am I looking at, and what should I do next"

---

## 5. Scope

### 5.1 In Scope (included in this version)
- Photo-based crop disease classification (38 crop-disease combinations)
- LLM-based explanation generation for diagnostic results
- Treatment product recommendations based on a pre-built disease-to-pesticide mapping database
- Automatic comparison and warning between expected harvest date and pesticide pre-harvest interval (PLS-based)
- Post-treatment follow-up notification (re-photo request → improvement assessment)

### 5.2 Out of Scope (excluded from this version)
- One-click payment/purchase integration (excluded due to legal risk and development scope; recommendations only, no purchase link)
- Conversational intake (a multi-turn chatbot feature that narrows down low-confidence cases by asking follow-up questions) — deferred to the roadmap
- Accessibility expansion features such as dialect-aware speech recognition, KakaoTalk chatbot deployment, ARS phone consultation
- Village/co-op-level dashboards, family-linked notifications

---

## 6. Functional Requirements

### FR-1. Image Diagnosis
- When a user uploads a photo of a crop leaf, the trained image classification model classifies it into one of 38 classes
- The classification result is returned along with a confidence score

### FR-2. Explainable Diagnosis
- The classification result (crop name, disease name) is passed to the LLM
- The LLM does not make a new diagnosis — it generates an explanation based solely on the already-confirmed classification result
- Output items: diagnosis result / disease characteristics (tailored to the user's level) / cause / recommended response

### FR-3. Personalized Treatment Recommendation
- Candidate products effective against the diagnosed disease are retrieved from a pre-built disease-to-pesticide mapping DB
- Candidates are further narrowed based on the user's conditions (farming purpose, organic status, etc. — to be further specified)

### FR-4. Safety Standard (PLS) Check
- Compares the user's expected harvest date against the recommended product's pre-harvest interval
- If there is a conflict, displays a warning message and suggests an alternative product

### FR-5. Follow-up
- Sends a follow-up reminder to the user a set period (e.g., 3–5 days) after the treatment guidance is given
- When a re-photo is uploaded, assesses whether the condition has improved; if not, guides the user toward re-diagnosis of the underlying cause

---

## 7. User Flow

```
Take/upload a photo
      ↓
Image classification model (InceptionV3, Transfer Learning) → crop-disease classification + confidence
      ↓
LLM-based explanation generation
      ↓
Disease-to-pesticide DB matching → personalized treatment recommendation
      ↓
Automatic PLS safety check (expected harvest date vs. pre-harvest interval)
      ↓
[Treatment applied]
      ↓
Follow-up reminder after N days → re-photo request → improvement assessment
```

---

## 8. Technical Requirements

### 8.1 Model
- **Architecture**: InceptionV3 (GoogLeNet family), ImageNet pretrained
- **Training method**: Transfer learning + fine-tuning
  - Early, low-level feature layers are frozen
  - Later layers plus the new 38-class output layer are retrained
- **Rationale for selection**: In the original PlantVillage dataset paper (Mohanty, Hughes & Salathé, 2016), which compared 60 experimental configurations, the GoogLeNet + transfer learning + color image combination achieved the highest accuracy (99.34%)
- **Evaluation metrics**: Accuracy, F1 Score, Confusion Matrix

### 8.2 Data
| Item | Description |
|---|---|
| Original data | PlantVillage (Hughes & Salathé, 2015), 54,306 images, captured in a controlled environment with a single background |
| Data used | New Plant Diseases Dataset (Kaggle, augmented), 87,000+ images |
| Number of classes | 14 crops × 26 disease types → 38 unique classes (the same disease on a different crop is treated as a separate class) |
| Data split | Train / Validation / Test (exact ratio TBD; the original paper's best performance was at an 80–20 split) |

### 8.3 LLM Pipeline
- Input: only the confirmed classification result (crop name, disease name) is passed — the LLM does not re-diagnose the image itself
- Output: a structured explanation (diagnosis result / cause / recommended response / safety information)
- Pesticide recommendations and pre-harvest interval information are not generated by the LLM; they are drawn from a pre-built, confirmed database (to prevent hallucination)

### 8.4 Known Limitations (based on the original paper)
- A model trained in a controlled environment (single background, front-facing shots) can see a substantial drop in accuracy in real-world conditions (varied backgrounds and angles) — the original paper reported a drop to as low as 31%
- To mitigate this, the design must clearly flag low-confidence cases and use the follow-up loop to correct misdiagnoses after the fact

---

## 9. Competitive Analysis

| Evaluation Criteria | RDA Diagnostic App | Farmdy | KyungNong Chatbot | AgriSage |
|---|:---:|:---:|:---:|:---:|
| Explains diagnostic reasoning | X | △ | O | O |
| Personalized pesticide recommendation | X | X | O | O |
| Automatic PLS safety check | X | X | △ | O |
| Post-treatment follow-up | X | △ | X | O |
| **Total** | 0/4 | 1/4 | 2.5/4 | 4/4 |

**Key differentiator**: Every service surveyed stops at "providing a diagnosis," whereas AgriSage completes the full journey after diagnosis (explanation → personalized recommendation → safety check → follow-up).

---

## 10. Risks & Assumptions

| Item | Description |
|---|---|
| Model generalization risk | A model trained on controlled-environment data may show lower accuracy on real user photos (varied lighting, angles, and backgrounds) |
| LLM hallucination risk | Pesticide recommendations and safety information must always be generated strictly from the confirmed database — if the LLM generates these on its own, it creates a safety hazard |
| Database build-out risk | The actual scope and accuracy of the disease-to-pesticide mapping DB has not yet been finalized — this is a high-priority task |
| Legal risk | Direct sale of pesticides is subject to legal regulation, so this version provides recommendations only and does not connect to a purchase flow |

---

## 11. Roadmap (Future Considerations)

- Introduce conversational intake (an LLM feature that asks follow-up questions to narrow down low-confidence cases)
- Benchmark performance against newer architectures such as EfficientNet
- Improve model robustness using real-world (uncontrolled-environment) data
- Expand accessibility: voice guidance, KakaoTalk chatbot deployment, etc. (early-stage idea, out of scope for this version)

---

## 12. References

1. Mohanty, S. P., Hughes, D. P., & Salathé, M. (2016). Using Deep Learning for Image-Based Plant Disease Detection. *Frontiers in Plant Science*, 7:1419.
2. Ministry of Agriculture, Food and Rural Affairs, "Return-to-Farming Increased in 2025 Despite Decline in Domestic Migration" (June 25, 2026)
3. Nongmin Shinmun, "Number of Returning Farmers Falls Below 10,000... Returning Rural Residents See a Surprise Rebound" (June 23, 2025)
4. Nongsaro (nongsaro.go.kr), column on the "Cyber Plant Clinic"
5. Nongmin Shinmun, "[Expert's Eye] Complying with Pesticide Dosage — The First Step to Safe Farming" (December 19, 2024)
6. Rural Development Administration Pesticide Safety Information System, "Regulation of Pesticide Residues"
7. Ministry of Agriculture, Food and Rural Affairs, "What Is the PLS System?"
