"""Exposure/state regressions with synthetic pixels; not biometric calibration."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.imaging import CaptureError
from app.services.luminance import DARK_MESSAGE, luminance_check
from app.services.liveness import LiveCapture
from app.services.visibility import FaceVisibilityService
from conftest import encoded


def frame(value):
    return np.full((240, 320, 3), value, np.uint8)


def forbidden(*_args, **_kwargs):
    raise AssertionError('An underexposed image must not run inference')


@pytest.mark.parametrize('value,ready', [(0, False), (35, False), (36, True), (120, True)])
def test_luminance_boundary(value, ready):
    result = luminance_check(frame(value))
    assert result['ready'] is ready
    assert result['brightness'] == value
    if not ready:
        assert result['warnings'] == [{'code': 'too_dark', 'message': DARK_MESSAGE}]


def test_bright_background_cannot_hide_dark_guide_and_dark_background_does_not_veto_lit_face():
    image = frame(255)
    image[48:192,112:208] = 10
    assert not luminance_check(image)['ready']
    image[:] = 5
    image[48:192,112:208] = 100
    assert luminance_check(image)['ready']


@pytest.mark.parametrize('context', ['selfie', 'holding', 'document'])
def test_preview_rejects_dark_pixels_before_loading_any_models(client, context):
    verifier = client.app.state.verifier
    verifier.visibility = SimpleNamespace(inspect=forbidden)
    verifier.face = SimpleNamespace(faces=forbidden)
    verifier.pad = SimpleNamespace(score=forbidden)
    verifier.ocr = SimpleNamespace(load=forbidden)
    if context == 'selfie':
        result = verifier.inspect_capture(frame(10))
    else:
        result = verifier.inspect_auto_capture(frame(10), context)
        assert not result['complete']
    assert not result['ready'] and result['warnings'][0]['message'] == DARK_MESSAGE
    assert result['mode'] == 'exposure_precheck'
    assert 'pad' not in result and '_document_reading' not in result


def test_detected_face_crop_stops_attributes_hands_and_pad_even_with_bright_surround(client):
    image = frame(140)
    image[30:110,20:100] = 10
    visibility = FaceVisibilityService.__new__(FaceVisibilityService)
    visibility.face = SimpleNamespace(faces=lambda _: [np.array([20,30,80,80])])
    visibility.attributes = SimpleNamespace(predict=forbidden)
    visibility.landmarks = SimpleNamespace(hands=forbidden)
    verifier = client.app.state.verifier
    verifier.visibility = visibility
    verifier.face = visibility.face
    verifier.pad = SimpleNamespace(score=forbidden)
    assert luminance_check(image)['ready']
    result = verifier.inspect_capture(image)
    assert not result['ready'] and result['face_box'] == [20,30,80,80]
    assert result['luminance']['scope'] == 'detected_face'
    assert result['warnings'][0]['message'] == DARK_MESSAGE


def test_dark_liveness_frame_resets_only_unfinished_action_and_adds_no_pad_or_selfie(client):
    capture = LiveCapture(['blink','turn','smile'])
    capture.gestures.completed = [{'challenge': 'blink'}]
    capture.gestures.baseline = {'blink': .3, 'yaw': 0, 'smile': .5}
    capture.gestures.hits = 1
    capture.pad_box_history = [[20,20,100,100]]
    result = client.app.state.verifier.inspect_liveness_frame(capture, frame(10), 'dark', 0)
    assert not result['done'] and not result['passed']
    assert result['feedback']['warnings'][0]['code'] == 'too_dark'
    assert capture.gestures.completed == [{'challenge': 'blink'}]
    assert capture.gestures.baseline is None
    assert not capture.pad_samples and capture.selfie_hash is None and not capture.evidence_images
    assert not capture.pad_box_history


def test_document_and_legacy_liveness_reject_dark_before_model_loading(client, monkeypatch):
    verifier = client.app.state.verifier
    monkeypatch.setattr(verifier, 'load', forbidden)
    with pytest.raises(CaptureError, match=DARK_MESSAGE):
        verifier.document(frame(10))
    result = verifier.evaluate_liveness(None, frame(120), [frame(10)], [])
    assert not result['passed'] and result['reason'] == DARK_MESSAGE


@pytest.mark.parametrize('stage', ['liveness', 'holding'])
def test_final_verification_keeps_underexposure_as_capture_retry_not_a_zero_ai_score(client, monkeypatch, stage):
    verifier = client.app.state.verifier
    monkeypatch.setattr(verifier, 'load', forbidden)
    session = SimpleNamespace(id='light-fixture', attempt=1,
        document_result={'fields': {'nik': '1234567890123456', 'name': 'PEMOHON UJI', 'birth': '1990-01-01'}})
    selfie, holding = frame(120), frame(120)
    if stage == 'liveness': selfie[:] = 10
    else: holding[:] = 10
    result = verifier.run(session, selfie, holding, [], [])
    assert result['status'] == 'capture' and result['retry']['stage'] == stage
    assert result['reason'] == DARK_MESSAGE
    assert not result['scores']


def start(client):
    session = client.post('/api/sessions').json()
    state = client.app.state.sessions.get(session['id'])
    state.document = frame(120)
    state.document_result = {'fields': {'nik': '1234567890123456'}}
    capture = client.post(f"/api/sessions/{state.id}/liveness/start").json()
    return state, capture


def test_server_dark_frame_and_no_image_pause_never_issue_proof_or_consume_extra_frames(client):
    state, started = start(client)
    path = f'/api/sessions/{state.id}/liveness'
    dark = client.post(path+'/frame', data={'capture_nonce': started['capture_nonce'], 'seq': 0},
                       files={'image': ('dark.jpg', encoded(frame(10)), 'image/jpeg')})
    assert dark.status_code == 200, dark.text
    assert not dark.json()['done'] and not dark.json()['passed']
    assert dark.json()['feedback']['warnings'][0]['message'] == DARK_MESSAGE
    assert state.liveness_proof is None and state.liveness_selfie is None
    state.stream_state.gestures.completed = [{'challenge': 'blink'}]
    state.stream_state.gestures.baseline = {'blink': .3}
    state.stream_state.spoof_strikes = 1
    paused = client.post(path+'/pause', data={'capture_nonce': started['capture_nonce'], 'seq': 1})
    assert paused.status_code == 200 and paused.json() == {'paused': True, 'frames': 1}
    assert state.stream_state.gestures.baseline is None
    assert state.stream_state.gestures.completed == [{'challenge': 'blink'}]
    assert state.stream_state.sequence == 1 and not state.stream_state.pad_samples
    assert state.stream_state.spoof_strikes == 1
    assert state.liveness_proof is None
    for data in [{'capture_nonce': 'wrong', 'seq': 1},
                 {'capture_nonce': started['capture_nonce'], 'seq': 0}]:
        assert client.post(path+'/pause', data=data).status_code == 409
    state.liveness_processing = True
    assert client.post(path+'/pause', data={'capture_nonce': started['capture_nonce'], 'seq': 1}).status_code == 409


def test_new_capture_and_expired_capture_cannot_be_paused_with_old_binding(client):
    state, old = start(client)
    path = f'/api/sessions/{state.id}/liveness'
    current = client.post(path+'/start').json()
    assert client.post(path+'/pause', data={'capture_nonce': old['capture_nonce'], 'seq': 0}).status_code == 409
    state.stream_state.started -= 100
    response = client.post(path+'/pause', data={'capture_nonce': current['capture_nonce'], 'seq': 0})
    assert response.status_code == 422
    assert state.liveness_proof is None
