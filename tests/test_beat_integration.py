"""Test Story Beats + NPCMind Integration"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("=" * 60)
print("STORY BEATS + NPCMIND INTEGRATION TEST")
print("=" * 60)

# Test setup
from luna.systems.world import WorldLoader
from luna.core.story_director import StoryDirector
from luna.systems.npc_mind import NPCMindManager, NPCMind
from luna.systems.world_simulator import WorldSimulator
from luna.core.models import GameState, TimeOfDay

print("\n[1] Loading world...")
loader = WorldLoader()
world = loader.load_from_folder("worlds/school_life_complete")
print(f"  ✓ World: {world.name}")
print(f"  ✓ Narrative arc beats: {len(world.narrative_arc.beats)}")

print("\n[2] Creating systems...")
story_director = StoryDirector(world.narrative_arc)
mind_manager = NPCMindManager()
tension_tracker = None  # Not needed for this test

sim = WorldSimulator(
    mind_manager=mind_manager,
    world=world,
    tension_tracker=tension_tracker,
    story_director=story_director
)
print("  ✓ StoryDirector created")
print("  ✓ WorldSimulator created with story_director")

print("\n[3] Creating game state (Maria affinity = 55)...")
gs = GameState(
    session_id=1,
    world_id="test",
    turn_count=10,
    current_location="school_classroom",
    active_companion="Maria",
    affinity={"Maria": 55, "Luna": 10, "Stella": 5},
    time_of_day=TimeOfDay.MORNING
)

# Register Maria's mind
maria_mind = mind_manager.get_or_create("Maria", name="Maria", is_companion=True)
print(f"  ✓ Maria mind created")

print("\n[4] Testing _process_story_beats...")
try:
    sim._process_story_beats(gs, turn=10)
    
    if maria_mind.current_goal:
        print(f"  ✓ Goal created!")
        print(f"    Description: {maria_mind.current_goal.description}")
        print(f"    Urgency: {maria_mind.current_goal.urgency}")
        print(f"    Source: {maria_mind.current_goal.source}")
        print(f"    Type: {maria_mind.current_goal.goal_type.value}")
    else:
        print(f"  ℹ No goal created (beat may not be active)")
        
    if maria_mind.emotions:
        print(f"  ✓ Emotions added:")
        for e in maria_mind.emotions:
            print(f"    - {e.emotion.value}: {e.intensity}")
            
except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n[5] Testing with lower affinity (Maria = 15)...")
gs2 = GameState(
    session_id=2,
    world_id="test",
    turn_count=10,
    current_location="school_classroom",
    active_companion="Maria",
    affinity={"Maria": 15, "Luna": 10, "Stella": 5},
    time_of_day=TimeOfDay.MORNING
)

maria_mind2 = mind_manager.get_or_create("Maria_low", name="Maria", is_companion=True)
maria_mind2.current_goal = None  # Reset

try:
    sim._process_story_beats(gs2, turn=11)
    
    if maria_mind2.current_goal:
        print(f"  ✗ Unexpected goal created!")
    else:
        print(f"  ✓ No goal created (affinity too low, correct behavior)")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n[6] Testing with Luna (affinity = 45)...")
gs3 = GameState(
    session_id=3,
    world_id="test",
    turn_count=10,
    current_location="school_classroom",
    active_companion="Luna",
    affinity={"Maria": 15, "Luna": 45, "Stella": 5},
    time_of_day=TimeOfDay.MORNING
)

luna_mind = mind_manager.get_or_create("Luna_test", name="Luna", is_companion=True)

try:
    sim._process_story_beats(gs3, turn=12)
    
    if luna_mind.current_goal:
        print(f"  ✓ Luna goal created!")
        print(f"    Description: {luna_mind.current_goal.description}")
        print(f"    Source: {luna_mind.current_goal.source}")
    else:
        print(f"  ℹ No goal (Luna beats need higher affinity)")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n" + "=" * 60)
print("✅ INTEGRATION TEST COMPLETE")
print("=" * 60)
print("\nSe il test ha creato goal per Maria e Luna,")
print("l'integrazione Story Beats + NPCMind funziona!")
