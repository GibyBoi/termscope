"""Unit tests for the Endpointer state machine (no audio devices needed).

Run: python sidecar/test_endpointer.py
"""
import numpy as np

from listen import (
    Endpointer,
    MAX_UTTERANCE,
    MIN_UTTERANCE,
    PRE_ROLL,
    SILENCE_HANG,
)

RATE = 16000


def feed_all(ep, samples, chunk=1600):
    """Feed samples in capture-sized chunks; collect emitted utterances."""
    out = []
    for i in range(0, len(samples), chunk):
        out.extend(ep.feed(samples[i : i + chunk]))
    return out


def speech(seconds, level=0.3):
    """Loud pseudo-speech: noise well above the silence floor."""
    rng = np.random.default_rng(42)
    return (rng.standard_normal(int(RATE * seconds)) * level).astype(np.float32)


def quiet(seconds):
    return np.zeros(int(RATE * seconds), dtype=np.float32)


def test_pause_ends_utterance():
    ep = Endpointer(RATE, np)
    utts = feed_all(ep, np.concatenate([quiet(0.5), speech(2.0), quiet(1.0)]))
    assert len(utts) == 1, f"expected 1 utterance, got {len(utts)}"
    utt, forced = utts[0]
    assert not forced
    # Roughly the speech plus pre/post padding — never the whole silence.
    assert int(RATE * 1.9) < len(utt) < int(RATE * (2.0 + 2 * PRE_ROLL) + RATE * 0.3)
    print("ok: a pause ends the utterance (len %.2fs)" % (len(utt) / RATE))


def test_idle_buffers_only_preroll():
    ep = Endpointer(RATE, np)
    assert feed_all(ep, quiet(10.0)) == []
    assert len(ep._buf) <= int(RATE * PRE_ROLL) + 1600
    print("ok: idle silence keeps only the pre-roll")


def test_short_blip_is_dropped():
    ep = Endpointer(RATE, np)
    blip = np.concatenate([quiet(0.3), speech(MIN_UTTERANCE / 3), quiet(1.0)])
    assert feed_all(ep, blip) == []
    print("ok: sub-minimum blips are dropped")


def test_long_speech_forces_split_without_overlap():
    ep = Endpointer(RATE, np)
    total = MAX_UTTERANCE + 4.0
    # Continuous loud speech with one soft dip near where the cut should land,
    # so the quietest-spot search has a best answer.
    s = speech(total)
    dip_at = int(RATE * (MAX_UTTERANCE - 0.8))
    s[dip_at : dip_at + int(RATE * 0.12)] *= 0.02
    utts = feed_all(ep, np.concatenate([s, quiet(1.0)]))
    assert len(utts) == 2, f"expected 2 utterances, got {len(utts)}"
    (u1, forced1), (u2, forced2) = utts
    assert forced1 and not forced2
    # A split, never an overlap: pieces must re-assemble to <= the input length.
    assert len(u1) + len(u2) <= len(s) + int(RATE * (2 * PRE_ROLL + SILENCE_HANG))
    # The forced cut landed inside the engineered dip (± the span width).
    assert abs(len(u1) - dip_at) < int(RATE * 0.3), f"cut at {len(u1)/RATE:.2f}s, dip at {dip_at/RATE:.2f}s"
    print("ok: long speech splits at the quietest spot (cut %.2fs, dip %.2fs)" % (len(u1) / RATE, dip_at / RATE))


def test_two_utterances_come_out_separately():
    ep = Endpointer(RATE, np)
    utts = feed_all(
        ep,
        np.concatenate([speech(1.0), quiet(1.0), speech(1.5), quiet(1.0)]),
    )
    assert len(utts) == 2
    assert not utts[0][1] and not utts[1][1]
    print("ok: separate utterances stay separate")


if __name__ == "__main__":
    test_pause_ends_utterance()
    test_idle_buffers_only_preroll()
    test_short_blip_is_dropped()
    test_long_speech_forces_split_without_overlap()
    test_two_utterances_come_out_separately()
    print("all endpointer tests passed")
