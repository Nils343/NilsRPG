from google import genai 
from pydantic import BaseModel
import os
import json

class Recipe(BaseModel):
    recipe_name: str
    ingredients: list[str]

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Start a streaming request with the same JSON‑schema config
stream = client.models.generate_content_stream(
    model='gemini-2.0-flash',
    contents='List two popular cookie recipes.',
    config={
        'temperature': 2,
        'response_mime_type': 'application/json',
        'response_schema': list[Recipe],
    },
)

# Accumulate the JSON text as it arrives
json_output = ''
for chunk in stream:
    # chunk.text is the next piece of JSON
    print(chunk.text, end='')  
    json_output += chunk.text

# Once the stream is done, parse the complete JSON string
recipes_data = json.loads(json_output)
my_recipes = [Recipe(**item) for item in recipes_data]

# Now you have a list of Recipe instances
for r in my_recipes:
    print(f"{r.recipe_name}: {r.ingredients}")
