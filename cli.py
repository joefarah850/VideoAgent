#!/usr/bin/env python3
"""
AI Video Agent – command line interface.

Usage examples:

  # Extract viral clips from a long video
  python cli.py clips my_talk.mp4 --n 5 --style "dramatic and inspiring"

  # Generate 3D animation ideas and produce one
  python cli.py animate "A lone astronaut discovering an ancient alien city" --duration 10

  # Brainstorm viral ideas for a niche
  python cli.py ideas "personal finance for millennials" --n 10

  # Clone your voice (run once, save the returned voice_id to .env)
  python cli.py clone-voice sample1.mp3 sample2.mp3 sample3.mp3

  # Generate voiceover from a script
  python cli.py voiceover "The world is changing faster than ever before..."

  # Full pipeline: chat with the agent
  python cli.py chat
"""
import argparse
import sys

from agent import run_agent


def cmd_chat(args):
    print("AI Video Agent – Interactive Mode")
    print("Type your request (or 'quit' to exit)\n")
    while True:
        try:
            request = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if request.lower() in ("quit", "exit", "q"):
            break
        if not request:
            continue
        run_agent(request)


def cmd_clips(args):
    request = (
        f"Extract the {args.n} most viral clips from the video at '{args.video}'. "
        f"Style: {args.style}. "
        "Transcribe it, find the best moments, extract each clip, add captions, "
        "and produce final composed clips ready for Instagram Reels."
    )
    run_agent(request)


def cmd_animate(args):
    request = (
        f"Create a {args.duration}-second 3D cinematic animation for this concept: '{args.concept}'. "
        "Craft an optimised text-to-video prompt first, then generate the animation."
    )
    run_agent(request)


def cmd_ideas(args):
    request = (
        f"Generate {args.n} viral short-form video ideas for the niche: '{args.niche}'. "
        "Also create a full script for the top idea."
    )
    run_agent(request)


def cmd_clone_voice(args):
    samples = args.samples
    request = (
        f"Clone my voice using these audio samples: {samples}. "
        "Name the voice 'MyVoice' and return the voice_id so I can add it to .env."
    )
    run_agent(request)


def cmd_voiceover(args):
    request = (
        f"Generate a voiceover for this script using my cloned voice: \"{args.script}\". "
        "Save the audio file and tell me the path."
    )
    run_agent(request)


def cmd_full_pipeline(args):
    request = (
        f"Run a full viral content pipeline for the video at '{args.video}':\n"
        "1. Transcribe the video\n"
        "2. Find the top 3 viral moments\n"
        "3. For each moment: extract the clip, add captions\n"
        "4. Generate a new voiceover narration for each clip using the cloned voice\n"
        "5. Compose final clips (portrait 9:16) ready for Instagram Reels\n"
        "Report the path of each final clip."
    )
    run_agent(request)


def main():
    parser = argparse.ArgumentParser(
        description="AI Video Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # chat
    p_chat = sub.add_parser("chat", help="Interactive chat with the agent")
    p_chat.set_defaults(func=cmd_chat)

    # clips
    p_clips = sub.add_parser("clips", help="Extract viral clips from a video")
    p_clips.add_argument("video", help="Path to source video")
    p_clips.add_argument("--n", type=int, default=5, help="Number of clips")
    p_clips.add_argument("--style", default="dramatic and epic", help="Clip style")
    p_clips.set_defaults(func=cmd_clips)

    # animate
    p_anim = sub.add_parser("animate", help="Generate 3D cinematic animation")
    p_anim.add_argument("concept", help="Animation concept/description")
    p_anim.add_argument("--duration", type=int, default=10, help="Duration in seconds")
    p_anim.set_defaults(func=cmd_animate)

    # ideas
    p_ideas = sub.add_parser("ideas", help="Generate viral content ideas")
    p_ideas.add_argument("niche", help="Content niche")
    p_ideas.add_argument("--n", type=int, default=10, help="Number of ideas")
    p_ideas.set_defaults(func=cmd_ideas)

    # clone-voice
    p_clone = sub.add_parser("clone-voice", help="Clone your voice with ElevenLabs")
    p_clone.add_argument("samples", nargs="+", help="Audio sample files (mp3/wav)")
    p_clone.set_defaults(func=cmd_clone_voice)

    # voiceover
    p_vo = sub.add_parser("voiceover", help="Generate voiceover from script")
    p_vo.add_argument("script", help="Narration script text")
    p_vo.set_defaults(func=cmd_voiceover)

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Full viral clip pipeline for a video")
    p_pipe.add_argument("video", help="Path to source video")
    p_pipe.set_defaults(func=cmd_full_pipeline)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
