from pathlib import Path


def _extract_service_block(compose_text: str, service_name: str) -> str:
    """Return the raw indented docker-compose service block."""
    service_header = f"  {service_name}:\n"
    lines = compose_text.splitlines()
    start_index = lines.index(service_header.rstrip("\n"))
    block_lines = [lines[start_index]]

    for line in lines[start_index + 1 :]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        block_lines.append(line)

    return "\n".join(block_lines)


def test_web_service_shares_sounds_volume_with_bot() -> None:
    """Web uploads must land in the same Sounds directory consumed by the bot."""
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")
    web_block = _extract_service_block(compose_text, "web")

    assert "/home/gabi/github/Discord-Brain-Rot/Sounds:/app/Sounds" in web_block
