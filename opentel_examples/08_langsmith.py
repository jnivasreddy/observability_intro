"""8. Native LangSmith: wrap supported SDK calls and annotate business functions."""
import os
from common import configure_logs, make_client, options, run, MODEL


def main():
    args = options(__doc__)
    if args.offline:
        os.environ["LANGSMITH_TRACING"] = "false"
    else:
        if not os.getenv("LANGSMITH_API_KEY"):
            raise ValueError("Add LANGSMITH_API_KEY to session_1_monitoring/.env for the hosted step")
        os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGSMITH_PROJECT", "order-assistant-examples")
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree
    from langsmith.wrappers import wrap_openai

    log = configure_logs(args, "08_langsmith.log")
    smith = Client() if not args.offline else None
    with make_client(args) as raw_client:
        client = wrap_openai(raw_client, tracing_extra={"client": smith} if smith else {})

        @traceable(name="calculate_refund", run_type="tool", client=smith)
        def calculate_refund(amount_paid, fee):
            refund = amount_paid - fee
            log.info("Refund calculated: refund=%s", refund)
            return refund

        @traceable(name="answer_question", client=smith)
        def answer_question(user_id, question):
            active = get_current_run_tree()
            log.info("Request received: user=%s langsmith_run_id=%s", user_id, active.id if active else "disabled")
            refund = calculate_refund(1200, 100)
            response = client.chat.completions.create(model=MODEL, messages=[{
                "role": "user", "content": question + f" The application calculated the refund as INR {refund}."}])
            log.info("Returning answer")
            return response.choices[0].message.content

        try:
            print(answer_question("A", args.question))
        finally:
            if smith:
                smith.flush()  # Finish sending records before this short-lived script exits.
    if args.offline:
        print("Offline wrapper check completed. Upload is disabled; no LangSmith dashboard trace was created.")
    else:
        print("Open LangSmith project: " + os.environ["LANGSMITH_PROJECT"])


if __name__ == "__main__":
    run(main)
