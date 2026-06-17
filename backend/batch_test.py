import asyncio
import httpx
import json
import re

TEST_INPUTS = [
    "The user must be able to reset their password using a link sent to their registered email.",
    "Admin dashboard should load within 2 seconds for up to 10,000 concurrent users.",
    "System must automatically log out users after 15 minutes of inactivity.",
    "Checkout process should support credit cards, PayPal, and Apple Pay.",
    "When an item goes out of stock, it should immediately be unlisted from the search page.",
    "Customer support agents need a button to issue a full refund within 30 days of purchase.",
    "The mobile app should cache product images for offline viewing.",
    "Users must verify their phone number via SMS before posting a new listing.",
    "Data backup must occur nightly at 2:00 AM UTC and be stored encrypted.",
    "The search bar should support fuzzy matching and typo tolerance."
]

async def run_batch():
    results = []
    url = "http://localhost:8000/api/run"
    
    async with httpx.AsyncClient(timeout=6000.0) as client:
        for i, text in enumerate(TEST_INPUTS):
            print(f"Running Test {i+1}/10...")
            payload = {
                "input_text": text,
                "num_generators": 2,
                "num_judges": 1,
                "execution_mode": "sequential",
                "model": "lfm2.5-thinking"
            }
            
            test_res = {
                "input": text,
                "triage_requirements": [],
                "generators": [],
                "judges": [],
                "consensus_text": "",
                "average_score": 0,
                "completion_time_ms": 0
            }
            
            try:
                async with client.stream("POST", url, json=payload) as response:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line.split(":", 1)[1].strip())
                                event_type = line.split(":", 1)[0] # Wait, this is 'data', the event is above.
                                # Let's assume pipeline_complete is the one with total_duration_ms
                                if "total_duration_ms" in data and "average_score" in data:
                                    test_res["triage_requirements"] = data.get("all_requirements", [])
                                    test_res["average_score"] = data.get("average_score", 0)
                                    test_res["completion_time_ms"] = data.get("total_duration_ms", 0)
                                    
                                    for g in data.get("generator_details", []):
                                        test_res["generators"].append({"score": g.get("final_score", 0)})
                                        
                                    jd = data.get("judge_details", [])
                                    if jd:
                                        raw_eval = jd[0].get("evaluation", "")
                                        # Clean think tags
                                        clean_eval = re.sub(r"<think>.*?</think>", "", raw_eval, flags=re.DOTALL)
                                        clean_eval = re.sub(r"<think>.*$", "", clean_eval, flags=re.DOTALL).strip()
                                        test_res["consensus_text"] = clean_eval
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                print(f"Error on test {i+1}: {e}")
                test_res["error"] = str(e)
                
            results.append(test_res)
            print(f"Test {i+1} done. Score: {test_res['average_score']}")
            
            # Write checkpoint
            with open("batch_results.json", "w") as f:
                json.dump(results, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_batch())
