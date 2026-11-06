# Security, Privacy & AI Trust Architecture (`design/security_architecture.md`)

- **Perspective:** **Security, Privacy, Compliance & AI Trust Architecture (Defense-in-Depth Zero-Trust Perimeters & AI Guardrails)**
- **Visual Archetype:** 5-Layer Defense-in-Depth Security & AI Trust Stack (`./diagrams/security_architecture.svg`)
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Defense-in-Depth & AI Trust Security Architecture Diagram

![Security Architecture](./diagrams/security_architecture.svg)

---

## 2. Threat Model, Security Controls & AI Trust Matrix

| Security Perimeter | Threat Vector Mitigated | Mandatory Control Implemented | Automated Verification Gate |
| :-- | :-- | :-- | :-- |
| **1. Identity & Federation** | Stolen static credentials or unauthenticated access | OIDC/SAML 2.0 federation + keyless `Workload Identity` | `TC-SEC-*` & KRM Non-Root / Identity Policy Gates |
| **2. Network & Edge** | Man-in-the-middle, DDoS, lateral network scanning | TLS 1.3, WAF, `Service Mesh STRICT mTLS`, private subnets | `deploy/gdc/service-mesh/` PeerAuthentication (`STRICT`) |
| **3. Application RBAC & State Guards** | Privilege escalation, self-approval, out-of-order state mutation | Server-side `(fromState, trigger, actorRole)` gate (`403`/`409`/`422`) | `TC-STATE-*` & `TC-NEG-*` Runtime Security Verification |
| **4. AI Trust & Privacy Boundary** | Raw PII/TIN leakage or internal column/enum exposure in UI/AI | Zero-Leak DTO projection + PII masking (`***-**-1234`) + AI prompt guardrails | `TC-UI-LEAK-*` Zero-Leakage Verification |
| **5. Data Encryption & Compliance** | Disk theft, container root breakout, audit log tampering | KMS CMEK encryption, append-only audit log, OPA non-root admission | OPA Policy Controller Admission Constraints |
