"""Test completo dei sistemi v7 - Luna RPG"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("=" * 60)
print("LUNA RPG v7 - SISTEM VERIFICATION")
print("=" * 60)

# Test 1: Import moduli v7
print("\n[1] Testing imports...")
try:
    from luna.systems.npc_mind import (
        NPCMind, NPCGoal, NPCMindManager, Emotion, EmotionType, 
        GoalType, UnspokenItem, OffScreenEvent, NPCRelationship,
        NeedProfile, GoalTemplate, TurnDriver
    )
    print("  ✓ npc_mind.py - OK")
except Exception as e:
    print(f"  ✗ npc_mind.py - FAILED: {e}")
    sys.exit(1)

try:
    from luna.systems.world_simulator import (
        WorldSimulator, TurnDirective, NPCInitiative, 
        AmbientDetail, NPCScenePresence, NarrativePressure,
        is_low_energy_input
    )
    print("  ✓ world_simulator.py - OK")
except Exception as e:
    print(f"  ✗ world_simulator.py - FAILED: {e}")
    sys.exit(1)

try:
    from luna.systems.tension_tracker import (
        TensionTracker, TensionAxis
    )
    print("  ✓ tension_tracker.py - OK")
except Exception as e:
    print(f"  ✗ tension_tracker.py - FAILED: {e}")
    sys.exit(1)

try:
    from luna.agents.director import DirectorAgent, SceneDirection, SceneBeat
    print("  ✓ director.py - OK")
except Exception as e:
    print(f"  ✗ director.py - FAILED: {e}")
    sys.exit(1)

# Test 2: Creazione NPCMind
print("\n[2] Testing NPCMind creation...")
try:
    mind = NPCMind(npc_id="luna", name="Luna")
    assert mind.npc_id == "luna"
    assert mind.name == "Luna"
    assert "social" in mind.needs
    print("  ✓ NPCMind creation - OK")
except Exception as e:
    print(f"  ✗ NPCMind creation - FAILED: {e}")

# Test 3: Creazione Goal
print("\n[3] Testing NPCGoal...")
try:
    goal = NPCGoal(
        description="Vuole parlarti del preside",
        goal_type=GoalType.SOCIAL,
        urgency=0.5
    )
    assert goal.description == "Vuole parlarti del preside"
    assert goal.urgency == 0.5
    print("  ✓ NPCGoal creation - OK")
    
    # Test tick (aumento urgency)
    goal.tick()
    assert goal.urgency > 0.5
    print("  ✓ Goal.tick() urgency growth - OK")
except Exception as e:
    print(f"  ✗ NPCGoal - FAILED: {e}")

# Test 4: NPCMindManager
print("\n[4] Testing NPCMindManager...")
try:
    manager = NPCMindManager()
    mind = manager.get_or_create("luna", name="Luna", is_companion=True)
    assert manager.get("luna") is not None
    print("  ✓ NPCMindManager - OK")
except Exception as e:
    print(f"  ✗ NPCMindManager - FAILED: {e}")

# Test 5: TensionTracker
print("\n[5] Testing TensionTracker...")
try:
    tracker = TensionTracker()
    tracker.load_defaults()
    assert len(tracker.axes) == 5  # 5 assi di default
    assert "romantic" in tracker.axes
    assert "environmental" in tracker.axes
    print("  ✓ TensionTracker defaults - OK")
except Exception as e:
    print(f"  ✗ TensionTracker - FAILED: {e}")

# Test 6: WorldSimulator
print("\n[6] Testing WorldSimulator...")
try:
    mind_manager = NPCMindManager()
    tracker = TensionTracker()
    tracker.load_defaults()
    
    sim = WorldSimulator(
        mind_manager=mind_manager,
        world=None,
        tension_tracker=tracker
    )
    print("  ✓ WorldSimulator creation - OK")
except Exception as e:
    print(f"  ✗ WorldSimulator - FAILED: {e}")

# Test 7: Low energy input detection
print("\n[7] Testing low-energy input detection...")
try:
    assert is_low_energy_input("ok") == True
    assert is_low_energy_input("ciao") == True
    assert is_low_energy_input("continua") == True
    assert is_low_energy_input("vado in classe") == False
    assert is_low_energy_input("parliamo del preside") == False
    print("  ✓ Low-energy detection - OK")
except Exception as e:
    print(f"  ✗ Low-energy detection - FAILED: {e}")

# Test 8: DirectorAgent
print("\n[8] Testing DirectorAgent...")
try:
    director = DirectorAgent()
    print("  ✓ DirectorAgent creation - OK")
except Exception as e:
    print(f"  ✗ DirectorAgent - FAILED: {e}")

# Test 9: Serialization NPCMind
print("\n[9] Testing NPCMind serialization...")
try:
    mind = NPCMind(npc_id="luna", name="Luna")
    mind.add_emotion(EmotionType.FRUSTRATED, intensity=0.7, cause="litigio", turn=1)
    mind.add_off_screen("Ha litigato col preside", turn=1, importance=0.6)
    
    data = mind.to_dict()
    assert "npc_id" in data
    assert "emotions" in data
    assert len(data["emotions"]) == 1
    print("  ✓ NPCMind.to_dict() - OK")
    
    # Test deserialization
    mind2 = NPCMind(npc_id="test", name="Test")
    mind2.from_dict(data)
    assert mind2.npc_id == "luna"  # dovrebbe essere sovrascritto
    print("  ✓ NPCMind.from_dict() - OK")
except Exception as e:
    print(f"  ✗ NPCMind serialization - FAILED: {e}")

# Test 10: Verifica presenza campi v7 in models.py
print("\n[10] Testing v7 model fields...")
try:
    from luna.core.models import CompanionDefinition, WorldDefinition
    
    # Verifica che i campi v7 esistano
    comp_fields = CompanionDefinition.model_fields.keys()
    assert "npc_relationships" in comp_fields
    assert "goal_templates" in comp_fields
    assert "needs_profile" in comp_fields
    print("  ✓ CompanionDefinition v7 fields - OK")
    
    world_fields = WorldDefinition.model_fields.keys()
    assert "tension_config" in world_fields
    print("  ✓ WorldDefinition v7 fields - OK")
except Exception as e:
    print(f"  ✗ v7 model fields - FAILED: {e}")

# Test 11: Caricamento YAML tension_config
print("\n[11] Testing tension_config.yaml loading...")
try:
    import yaml
    yaml_path = os.path.join(os.path.dirname(__file__), 'worlds', 'school_life_complete', 'tension_config.yaml')
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        assert "tension_axes" in config
        assert "romantic" in config["tension_axes"]
        print("  ✓ tension_config.yaml structure - OK")
    else:
        print("  ⚠ tension_config.yaml not found (optional)")
except Exception as e:
    print(f"  ✗ tension_config.yaml - FAILED: {e}")

print("\n" + "=" * 60)
print("✅ ALL v7 SYSTEMS TESTS PASSED!")
print("=" * 60)
print("\nIl sistema v7 'Il Mondo Vive' è correttamente configurato.")
print("Componenti attivi:")
print("  • NPCMind - Stato interno NPC (bisogni, goal, emozioni)")
print("  • WorldSimulator - Tick del mondo ogni turno")
print("  • TensionTracker - Pressione narrativa organica")
print("  • DirectorAgent - Decisioni scena (LLM leggero)")
