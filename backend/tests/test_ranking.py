from app.audio import decode_pcm16_mono, measure_intrinsic, rank_set
from tests.audio_gen import write_wav


def test_synthetic_clean_outranks_noisy_and_clipped(tmp_path):
    clean = write_wav(tmp_path / "clean.wav", duration=2.2, kind="clean")
    noisy = write_wav(tmp_path / "noisy.wav", duration=2.2, kind="noisy")
    clipped = write_wav(tmp_path / "clipped.wav", duration=2.2, kind="clipped")
    short = write_wav(tmp_path / "short.wav", duration=0.8, kind="clean")

    items = []
    for rec_id, path in (("clean", clean), ("noisy", noisy), ("clipped", clipped), ("short", short)):
        samples = decode_pcm16_mono(path)
        # Duration from sample length keeps this test independent of container padding.
        duration = samples.size / 16000
        items.append((rec_id, measure_intrinsic(samples, duration)))
    qualities = rank_set(items)
    assert qualities["clean"]["score"] > qualities["noisy"]["score"]
    assert qualities["clean"]["score"] > qualities["clipped"]["score"]
    assert "clipping" in qualities["clipped"]["flags"]
    assert "possibly_incomplete" in qualities["short"]["flags"]
    # Honest limitation: this is a synthetic energy proxy, not a lecture-hall test.
    assert qualities["clean"]["coverageSec"] > qualities["short"]["coverageSec"]
