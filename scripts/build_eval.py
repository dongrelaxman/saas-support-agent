import csv, json

A = "answer"
H = "low_confidence_hedge"
P = "immediate_handoff"

rows = [
 # answerable (30): question, expected keywords, source doc
 ("How much is the Pro plan per user per month if I pay monthly?", "$12", "01_pricing_and_plans.md"),
 ("What does the Business plan cost per user on annual billing?", "$20", "01_pricing_and_plans.md"),
 ("How many projects can I have on the Free plan?", "3 projects", "01_pricing_and_plans.md"),
 ("Do I need a credit card to start the trial?", "no credit card; 14 days", "01_pricing_and_plans.md"),
 ("What's the maximum file size I can upload on Pro?", "2 GB", "01_pricing_and_plans.md"),
 ("How much storage do I get on the Free plan?", "2 GB", "01_pricing_and_plans.md"),
 ("Can I get a refund on my annual plan?", "14 days of first purchase", "02_refunds_and_cancellation.md"),
 ("Are monthly plans refundable?", "not refundable; cancel anytime", "02_refunds_and_cancellation.md"),
 ("How do I cancel my subscription?", "Settings > Billing > Cancel plan", "02_refunds_and_cancellation.md"),
 ("If I delete my account can I get it back?", "30-day grace period", "02_refunds_and_cancellation.md"),
 ("How do I change my payment method?", "Settings > Billing > Payment method", "03_billing_and_payments.md"),
 ("What happens if my payment fails?", "retry 3 times over 7 days; downgrade to Free", "03_billing_and_payments.md"),
 ("How long is the password reset link valid?", "30 minutes", "04_account_and_login.md"),
 ("How many wrong passwords before my account gets locked?", "5 attempts; 15 minutes", "04_account_and_login.md"),
 ("How do I invite someone to my workspace?", "Members > Invite", "04_account_and_login.md"),
 ("How many guests can I have for free?", "10 guests", "04_account_and_login.md"),
 ("How do I turn on two-factor authentication?", "Settings > Security; authenticator app", "05_security_and_2fa.md"),
 ("How many backup codes do I get with 2FA?", "10", "05_security_and_2fa.md"),
 ("Which plans include SSO?", "Business and Enterprise; SAML", "05_security_and_2fa.md"),
 ("Do you support SMS codes for 2FA?", "no SMS", "05_security_and_2fa.md"),
 ("How do I export my data?", "Settings > Data > Export; CSV or JSON", "06_data_export_and_retention.md"),
 ("How long do deleted projects stay in the trash?", "30 days", "06_data_export_and_retention.md"),
 ("Where is my data hosted?", "AWS us-east-1; EU eu-west-1", "06_data_export_and_retention.md"),
 ("Is TaskPilot SOC 2 certified?", "SOC 2 Type II", "06_data_export_and_retention.md"),
 ("Can I import my projects from Jira?", "Settings > Import > Jira; no attachments", "07_integrations.md"),
 ("What is the API rate limit on the Pro plan?", "600 requests per minute", "07_integrations.md"),
 ("What iOS version do I need for the mobile app?", "iOS 15", "08_mobile_apps.md"),
 ("Does the mobile app work offline?", "yes; 7 days", "08_mobile_apps.md"),
 ("What are your support hours?", "Mon-Fri 9am-6pm UTC", "09_support_and_sla.md"),
 ("How fast does the Business plan get a support response?", "within 4 hours", "09_support_and_sla.md"),
]
out_of_scope = [
 "Do you offer a lifetime deal?",
 "Is there a native Windows desktop app?",
 "Can TaskPilot integrate with Salesforce?",
 "Who is the CEO of TaskPilot?",
 "How do I reset my Netflix password?",
 "Does the Timeline view support critical path analysis?",
 "Do you offer discounts for nonprofits?",
 "What's the weather like in Berlin today?",
 "Can you sign a HIPAA BAA?",
 "Can I white-label TaskPilot with my own logo and domain?",
 "What's on your roadmap for AI features?",
 "How do I set up the TaskPilot Zapier integration?",
 "Can I self-host TaskPilot on my own servers?",
 "What is your guaranteed uptime SLA percentage?",
 "Do you offer phone support?",
]
handoff = [
 "I want to talk to a human",
 "Can I speak to a real person please?",
 "Connect me to an agent",
 "This bot is useless, get me a representative",
 "Transfer me to support staff",
]

with open("eval/eval_set.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["id","question","category","expected_behavior","expected_answer_keywords","source_doc"])
    i = 1
    for q, kw, src in rows:
        w.writerow([f"q{i:02d}", q, "in_scope", A, kw, src]); i += 1
    for q in out_of_scope:
        w.writerow([f"q{i:02d}", q, "out_of_scope", H, "", ""]); i += 1
    for q in handoff:
        w.writerow([f"q{i:02d}", q, "human_request", P, "", ""]); i += 1

convos = [
 {"id":"conv_happy_path",
  "description":"All answerable. Streak stays 0. No handoff.",
  "turns":["How much is Pro per month?","How do I enable 2FA?","What are your support hours?"],
  "expected_streak_after_each_turn":[0,0,0],
  "expected_final_status":"bot"},
 {"id":"conv_slow_failure",
  "description":"Three consecutive out-of-scope questions trigger handoff on turn 3.",
  "turns":["Do you offer a lifetime deal?","Can I self-host TaskPilot?","Do you offer phone support?"],
  "expected_streak_after_each_turn":[1,2,3],
  "expected_final_status":"awaiting_human"},
 {"id":"conv_streak_reset",
  "description":"Two misses, then a hit resets the streak, then one more miss. No handoff.",
  "turns":["Can TaskPilot integrate with Salesforce?","Is there a native Windows desktop app?","How long is the password reset link valid?","Do you offer discounts for nonprofits?"],
  "expected_streak_after_each_turn":[1,2,0,1],
  "expected_final_status":"bot"},
 {"id":"conv_explicit_request",
  "description":"Immediate handoff on turn 1 with no retrieval.",
  "turns":["I want to talk to a human"],
  "expected_streak_after_each_turn":[0],
  "expected_final_status":"awaiting_human"},
 {"id":"conv_late_request",
  "description":"Normal answer, then asks for a person on turn 2.",
  "turns":["What is the refund policy for annual plans?","Actually just connect me to an agent"],
  "expected_streak_after_each_turn":[0,0],
  "expected_final_status":"awaiting_human"},
 {"id":"conv_stale_doc_trap",
  "description":"Archived 2024 pricing doc must not win. Expected answer is $12, not $10.",
  "turns":["What does Pro cost per user per month, monthly billing?"],
  "expected_answer_keywords":["$12"],
  "forbidden_answer_keywords":["$10 per user per month billed monthly"],
  "expected_final_status":"bot"},
]
json.dump(convos, open("eval/conversations.json","w"), indent=2)
print("rows:", i-1, "convos:", len(convos))
