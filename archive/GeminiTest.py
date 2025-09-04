from google import genai
from pydantic import BaseModel
import os

class Recipe(BaseModel):
  recipe_name: str
  ingredients: list[str]

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
  
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents='List two popular cookie recipes.',
    config={
        'temperature':2,
        'response_mime_type': 'application/json',
        'response_schema': list[Recipe],
    },
)
# Use the response as a JSON string.
print(response.text)

# Use instantiated objects.
my_recipes: list[Recipe] = response.parsed