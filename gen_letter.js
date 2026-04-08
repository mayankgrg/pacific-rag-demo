const {
  Document, Packer, Paragraph, TextRun, AlignmentType
} = require('docx');
const fs = require('fs');

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: "Georgia", size: 24 } }
    }
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1260, right: 1260, bottom: 1260, left: 1260 }
      }
    },
    children: [
      // Header: Name
      new Paragraph({
        children: [new TextRun({ text: "Mayank Garg", bold: true, size: 32, font: "Georgia" })],
        alignment: AlignmentType.LEFT,
        spacing: { after: 40 }
      }),
      // Contact line
      new Paragraph({
        children: [new TextRun({ text: "mayankgrg  \u00b7  github.com/mayankgrg  \u00b7  builders@pacific.app submission", size: 20, color: "555555", font: "Georgia" })],
        alignment: AlignmentType.LEFT,
        spacing: { after: 40 },
        border: { bottom: { style: "single", size: 6, color: "CCCCCC", space: 1 } }
      }),
      // Spacer
      new Paragraph({ children: [new TextRun("")], spacing: { after: 160 } }),

      // Date + Salutation
      new Paragraph({
        children: [new TextRun({ text: "April 8, 2026", size: 22, font: "Georgia" })],
        spacing: { after: 160 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Annika Klein", size: 22, font: "Georgia" })],
        spacing: { after: 40 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Pacific", size: 22, font: "Georgia" })],
        spacing: { after: 160 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Dear Annika,", size: 22, font: "Georgia" })],
        spacing: { after: 200 }
      }),

      // Paragraph 1 — What I built
      new Paragraph({
        children: [new TextRun({
          text: "For this application I built a permission-aware RAG system: a web application where an AI assistant answers employee questions strictly from documents the logged-in user is authorized to see. The stack is FastAPI, ChromaDB, sentence-transformers, and Groq (llama-3.1-8b-instant). Employees authenticate via JWT; every query triggers a role-filtered vector search before the LLM is ever invoked, so restricted content is excluded at the retrieval layer, not patched over in the prompt. The same question asked by an intern and a finance lead produces completely different answers \u2014 or a clean \u201cno access\u201d \u2014 depending on what their role permits.",
          size: 22,
          font: "Georgia"
        })],
        alignment: AlignmentType.JUSTIFIED,
        spacing: { after: 200 }
      }),

      // Paragraph 2 — Technical depth
      new Paragraph({
        children: [new TextRun({
          text: "I built the permission layer around five Acme Corp documents across four access levels (public, internal, confidential, restricted). ChromaDB stores boolean role flags per chunk; at query time, expand_roles() resolves the user\u2019s role into all permitted tiers and builds a metadata filter before any embedding similarity is computed. On top of that sits bcrypt authentication, SameSite=Strict httpOnly cookies, an XSS-safe chat UI (textContent only, no innerHTML), prompt injection defense via XML tag isolation, rate limiting at 20 req/min per IP, security headers, and an audit log that records who asked what, which documents were returned, and how many chunks were blocked. An offline eval harness runs 25 role-permission tests; all 25 pass with zero leakage. The project also ships 149 unit tests across five modules covering every function, utility, and API endpoint \u2014 all 149 pass.",
          size: 22,
          font: "Georgia"
        })],
        alignment: AlignmentType.JUSTIFIED,
        spacing: { after: 200 }
      }),

      // Paragraph 3 — Why it fits Pacific
      new Paragraph({
        children: [new TextRun({
          text: "This maps directly onto the ECMS problem Pacific is solving. ECMS has to answer: \u201cwhat context is this agent actually allowed to see?\u201d My system answers that same question for human employees, using the same primitives \u2014 a role store (employees.json standing in for Okta), a permission-filtered retrieval engine, an LLM that only sees cleared context, and evaluation infrastructure to prove the trust boundary holds. The architecture is intentionally minimal so each layer is transparent and auditable, which I think is the right instinct for enterprise AI where a single context leak can be a compliance incident.",
          size: 22,
          font: "Georgia"
        })],
        alignment: AlignmentType.JUSTIFIED,
        spacing: { after: 200 }
      }),

      // Paragraph 4 — Why Pacific / close
      new Paragraph({
        children: [new TextRun({
          text: "I want to work at Pacific because the hard problems are in the infrastructure layer, not the demo layer. Getting permissions right, keeping latency low enough that agents can chain calls, building evals that catch regressions before they reach production \u2014 those are the problems I find genuinely interesting, and they\u2019re exactly what the ECMS internship is about. I\u2019d be glad to walk through the code or extend the project in any direction that\u2019s useful for the interview.",
          size: 22,
          font: "Georgia"
        })],
        alignment: AlignmentType.JUSTIFIED,
        spacing: { after: 240 }
      }),

      // Closing
      new Paragraph({
        children: [new TextRun({ text: "Thank you for your time.", size: 22, font: "Georgia" })],
        spacing: { after: 160 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Mayank Garg", bold: true, size: 22, font: "Georgia" })],
        spacing: { after: 40 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "github.com/mayankgrg/pacific-rag-demo", size: 20, color: "444444", font: "Georgia" })],
      }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("cover_letter.docx", buffer);
  console.log("cover_letter.docx written successfully.");
});
