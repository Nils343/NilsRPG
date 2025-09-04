import sys
import pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from models import GameResponse, Environment, InventoryItem, PerkSkill, Attributes


def test_game_response_parsing():
    data = {
        'day': 1,
        'time': 'morning',
        'current_situation': 'You wake up in a forest.',
        'environment': {
            'Location': 'Forest',
            'Daytime': 'Dawn',
            'Light': 'Dim',
            'Temperature': 'Cool',
            'Humidity': 'High',
            'Wind': 'Calm',
            'Soundscape': 'Birds chirping',
        },
        'inventory': [
            {'name': 'Sword', 'description': 'A sharp blade.', 'weight': 3.5, 'equipped': False}
        ],
        'perks_skills': [
            {'name': 'Stealth', 'degree': 'Novice', 'description': 'Move unseen.'}
        ],
        'attributes': {
            'Name': 'Hero',
            'Background': 'Adventurer',
            'Age': '25',
            'Health': 'Good',
            'Sanity': 'Stable',
            'Hunger': 'Satisfied',
            'Thirst': 'Quenched',
            'Stamina': 'High',
        },
        'options': ['Go north'],
        'image_prompt': 'A forest path at dawn.'
    }
    response = GameResponse(**data)
    assert response.environment.Location == 'Forest'
    assert response.inventory[0].equipped is False
    assert response.perks_skills[0].name == 'Stealth'
    assert response.attributes.Name == 'Hero'

