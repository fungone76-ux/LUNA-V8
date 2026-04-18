"""Test Story Beats implementation"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("=" * 60)
print("STORY BEATS VERIFICATION")
print("=" * 60)

# Test 1: Import
print("\n[1] Testing imports...")
try:
    from luna.systems.world import WorldLoader
    from luna.core.story_director import StoryDirector, BeatConditionEvaluator
    from luna.core.models import GameState, StoryBeat
    print("  ✓ Imports OK")
except Exception as e:
    print(f"  ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Caricamento world
print("\n[2] Loading world...")
try:
    loader = WorldLoader()
    world = loader.load_from_folder("worlds/school_life_complete")
    print(f"  ✓ World loaded: {world.name}")
    print(f"  ✓ Narrative arc beats: {len(world.narrative_arc.beats)}")
except Exception as e:
    print(f"  ✗ World load failed: {e}")
    sys.exit(1)

# Test 3: Verifica beats
print("\n[3] Verifying beats...")
if world.narrative_arc.beats:
    for beat in world.narrative_arc.beats[:3]:  # Primi 3
        print(f"  • {beat.id}: {beat.description[:50]}...")
        print(f"    Trigger: {beat.trigger}")
else:
    print("  ✗ No beats found!")

# Test 4: StoryDirector
print("\n[4] Testing StoryDirector...")
try:
    director = StoryDirector(world.narrative_arc)
    print(f"  ✓ StoryDirector created with {len(director.arc.beats)} beats")
except Exception as e:
    print(f"  ✗ StoryDirector failed: {e}")

# Test 5: Beat evaluation
print("\n[5] Testing beat evaluation...")
try:
    from luna.core.models import TimeOfDay
    
    gs = GameState(
        session_id=1,
        world_id="test",
        turn_count=10,
        current_location="school_classroom",
        active_companion="Maria",
        affinity={"Maria": 25, "Luna": 10, "Stella": 5},
        time_of_day=TimeOfDay.MORNING
    )
    
    evaluator = BeatConditionEvaluator()
    
    # Test vari trigger
    tests = [
        ("affinity_Maria >= 20", True),
        ("affinity_Luna >= 40", False),
        ("turn >= 5", True),
        ("location == school_classroom", True),
    ]
    
    for trigger, expected in tests:
        result = evaluator.evaluate(trigger, gs)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{trigger}' => {result} (expected {expected})")
    
except Exception as e:
    print(f"  ✗ Evaluation failed: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Active beat detection
print("\n[6] Testing active beat detection...")
try:
    beat = director.get_active_instruction(gs)
    if beat:
        print(f"  ✓ Active beat found: {beat[0].id}")
        print(f"    Description: {beat[0].description}")
    else:
        print("  ℹ No active beat (affinity too low for Maria)")
    
    # Test con affinity alta
    gs.affinity["Maria"] = 55
    beat = director.get_active_instruction(gs)
    if beat:
        print(f"  ✓ With affinity 55, active beat: {beat[0].id}")
    else:
        print("  ℹ Still no active beat")
        
except Exception as e:
    print(f"  ✗ Active beat detection failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ STORY BEATS TEST COMPLETE")
print("=" * 60)
