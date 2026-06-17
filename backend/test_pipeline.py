import httpx
import json
import asyncio

async def test_pipeline():
    url = "http://localhost:8000/api/run"
    payload = {
        "input_text": "The system shall allow users to securely upload PDF documents up to 5MB. If the document exceeds 5MB or is not a PDF, show an error. Otherwise, confirm upload success.",
        "num_generators": 2,
        "num_judges": 1,
        "execution_mode": "sequential",
        "model": "lfm2.5-thinking"
    }

    print("=== STARTING PIPELINE TEST (2 Generators, 1 Judge) ===")
    
    async with httpx.AsyncClient(timeout=3000.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                
                # Check for standard server-sent events format
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    print(f"[{event_type}]", end=" ")
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line.split(":", 1)[1].strip())
                        if "text" in data and event_type not in ["preprocessor_chunk", "generator_chunk", "judge_chunk"]:
                            # Ignore noisy text streaming chunks to keep output clean, unless you want them.
                            pass
                        elif "text" in data:
                            # Just print a dot for streaming chunks
                            print(".", end="", flush=True)
                        else:
                            # Print structural data summaries
                            if event_type == "preprocessor_done":
                                print(f"\n✅ Triage extracted: {len(data.get('requirements', []))} atomic requirements.")
                                for r in data.get("requirements", []):
                                    print(f"   - {r}")
                            elif event_type == "generator_done":
                                print(f"\n✅ Generator {data.get('id')} finished. ({data.get('duration_ms')}ms)")
                            elif event_type == "judge_done":
                                print(f"\n✅ Judge {data.get('id')} finished. ({data.get('duration_ms')}ms)")
                            elif event_type == "pipeline_complete":
                                print(f"\n🎉 PIPELINE COMPLETE! Total duration: {data.get('total_duration_ms')}ms\n")
                                print("===== CONSENSUS OUTPUT =====")
                                text = ""
                                judge_details = data.get("judge_details", [])
                                if judge_details:
                                    text = judge_details[0].get("evaluation", "")
                                import re
                                text_clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
                                text_clean = re.sub(r"<think>.*$", "", text_clean, flags=re.DOTALL).strip()
                                print(text_clean)
                    except json.JSONDecodeError:
                        print(f" [Raw Data]: {line}")
            print("\n=== TEST END ===")

if __name__ == "__main__":
    asyncio.run(test_pipeline())
