import pytest

from luna.media.builders.image_builder import ImagePromptBuilder


def test_image_prompt_builder_defaults_composition_when_none():
    builder = ImagePromptBuilder()

    prompt = builder.build(
        visual_description="Luna is teaching at the chalkboard",
        tags=["classroom", "teacher"],
        composition=None,
        character_name="Luna",
    )

    assert prompt.composition == "medium_shot"
    assert prompt.steps == 24
    assert prompt.cfg_scale == 7.0
    assert prompt.sampler == "euler"
    assert prompt.seed is None


def test_image_prompt_builder_keeps_explicit_composition():
    builder = ImagePromptBuilder()

    prompt = builder.build(
        visual_description="Close portrait of Luna smiling",
        tags=["close up", "portrait"],
        composition="close_up",
        character_name="Luna",
    )

    assert prompt.composition == "close_up"
