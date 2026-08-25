import inspect
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sportsmodel.dashboard.views import daily_moneyline as view
from sportsmodel.models.moneyline_live_dashboard import MoneylineLiveSlate


TARGET_DATE = date(2026, 8, 12)
STARTED_AT = datetime(2026, 8, 12, 15, tzinfo=timezone.utc)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        return False


class _FakeStreamlit:
    def __init__(self, *, clicked_keys=(), selected_option=None) -> None:
        self.session_state = {}
        self.clicked_keys = set(clicked_keys)
        self.selected_option = selected_option
        self.errors = []
        self.codes = []
        self.warnings = []
        self.writes = []
        self.markdowns = []

    def button(self, label, *, key, on_click, args=(), **kwargs):
        if key in self.clicked_keys:
            on_click(*args)
            return True
        return False

    def selectbox(self, *arguments, **kwargs):
        return self.selected_option

    def spinner(self, *arguments, **kwargs):
        return _Context()

    def expander(self, *arguments, **kwargs):
        return _Context()

    def container(self, *arguments, **kwargs):
        return _Context()

    def error(self, message):
        self.errors.append(message)

    def code(self, message):
        self.codes.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def write(self, message):
        self.writes.append(message)

    def markdown(self, message):
        self.markdowns.append(message)


def test_official_card_does_not_select_newer_preview(monkeypatch) -> None:
    official = _slate(
        prediction_run_id=44,
        snapshot_role="entry",
        run_type="official",
    )
    newer_preview = _slate(
        prediction_run_id=45,
        snapshot_role="late_night",
        run_type="preview",
    )
    monkeypatch.setattr(
        view,
        "_load_slates",
        lambda: (newer_preview, official),
    )

    assert view._find_latest_slate(target_date=TARGET_DATE) == official


def test_results_include_only_official_entry_slates() -> None:
    official = _slate(
        prediction_run_id=44,
        snapshot_role="entry",
        run_type="official",
    )
    preview = _slate(
        prediction_run_id=45,
        snapshot_role="late_night",
        run_type="preview",
    )

    assert view._latest_slate_per_date((preview, official)) == (official,)


def test_no_selection_performs_zero_explanation_loads(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: pytest.fail("explanation was loaded eagerly"),
    )

    view._render_explanation_control(_game(501))

    assert fake_st.session_state == {}


def test_selecting_and_switching_uses_only_the_active_prediction(monkeypatch) -> None:
    fake_st = _FakeStreamlit(
        clicked_keys={"moneyline_explanation_select_502"}
    )
    fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] = 501
    loaded = []
    rendered = []
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: (loaded.append(prediction_id) or object(), None),
    )
    monkeypatch.setattr(
        view,
        "_render_prediction_explanation_panel",
        lambda explanation: rendered.append(explanation),
    )

    view._render_explanation_control(_game(502))

    assert fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] == 502
    assert loaded == [502]
    assert len(rendered) == 1


def test_table_only_prediction_can_be_selected_on_demand(monkeypatch) -> None:
    fake_st = _FakeStreamlit(
        clicked_keys={"moneyline_explanation_picker_select_official"},
        selected_option=503,
    )
    loaded = []
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: (loaded.append(prediction_id) or object(), None),
    )
    monkeypatch.setattr(
        view,
        "_render_prediction_explanation_panel",
        lambda explanation: None,
    )

    view._render_explanation_selector((_game(503),), key_prefix="official")

    assert fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] == 503
    assert loaded == [503]


def test_switching_cards_moves_the_only_active_explanation(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] = 501
    loaded = []
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: (loaded.append(prediction_id) or object(), None),
    )
    monkeypatch.setattr(
        view,
        "_render_prediction_explanation_panel",
        lambda explanation: None,
    )

    view._render_explanation_control(_game(501))
    view._render_explanation_control(_game(502))
    assert loaded == [501]

    view._activate_prediction_explanation(502)
    loaded.clear()
    view._render_explanation_control(_game(501))
    view._render_explanation_control(_game(502))

    assert loaded == [502]


def test_close_clears_active_explanation(monkeypatch) -> None:
    fake_st = _FakeStreamlit(
        clicked_keys={"moneyline_explanation_close_501"}
    )
    fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] = 501
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: pytest.fail("closed explanation was loaded"),
    )

    view._render_explanation_control(_game(501))

    assert view.ACTIVE_EXPLANATION_STATE_KEY not in fake_st.session_state


def test_card_explanation_is_not_duplicated_by_selector_fallback(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] = 501
    loaded = []
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: (loaded.append(prediction_id) or object(), None),
    )
    monkeypatch.setattr(
        view,
        "_render_prediction_explanation_panel",
        lambda explanation: None,
    )

    game = _game(501)
    view._render_explanation_control(game)
    view._render_explanation_selector(
        (game,),
        key_prefix="official",
        rendered_card_prediction_ids={501},
    )

    assert loaded == [501]


def test_explanation_failure_is_visible_and_does_not_escape(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state[view.ACTIVE_EXPLANATION_STATE_KEY] = 501
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "_try_load_prediction_explanation",
        lambda prediction_id: (None, RuntimeError("historical state unavailable")),
    )

    view._render_active_prediction_explanation((_game(501),))

    assert len(fake_st.errors) == 1
    assert "dashboard is unaffected" in fake_st.errors[0]
    assert fake_st.codes == ["RuntimeError: historical state unavailable"]


def test_cached_loader_accepts_only_prediction_id_and_default_service_contract(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        view,
        "explain_moneyline_prediction",
        lambda **kwargs: calls.append(kwargs) or "result",
    )
    uncached_loader = view._load_prediction_explanation.__wrapped__

    assert uncached_loader(429) == "result"
    assert calls == [{"prediction_id": 429}]
    with pytest.raises(ValueError, match="greater than zero"):
        uncached_loader(0)
    source = inspect.getsource(view._load_prediction_explanation.__wrapped__)
    assert "reconstruction_tolerance" not in source


def test_non_authoritative_panel_returns_before_ranked_content(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(view, "st", fake_st)
    monkeypatch.setattr(
        view,
        "present_moneyline_prediction_explanation",
        lambda explanation: SimpleNamespace(
            title="Why Away Club 53.00%?",
            authoritative=False,
            authority_message="rankings are withheld",
        ),
    )
    explanation = SimpleNamespace(
        prediction=SimpleNamespace(
            stored_home_win_probability=Decimal("0.47"),
        ),
        reconstructed_home_win_probability=0.48,
        probability_delta=0.01,
        reconstruction_tolerance=1e-9,
        contributions=(SimpleNamespace(feature_name="must_not_render"),),
    )

    view._render_prediction_explanation_panel(explanation)

    rendered_text = " ".join(
        fake_st.markdowns + fake_st.writes + fake_st.warnings
    )
    assert "rankings are withheld" in rendered_text
    assert "Category leans" not in rendered_text
    assert "must_not_render" not in rendered_text


def test_cache_contract_and_raw_missing_caption_are_explicit() -> None:
    source = inspect.getsource(view)

    assert "@st.cache_data(ttl=60, show_spinner=False)" in source
    assert "Missing values:" not in source
    assert "Raw unavailable fields:" in source


def _game(prediction_id: int):
    return SimpleNamespace(
        moneyline_game_prediction_id=prediction_id,
        predicted_team_name="Away Club",
        model_probability=Decimal("0.53"),
    )


def _slate(
    *,
    prediction_run_id: int,
    snapshot_role: str,
    run_type: str,
) -> MoneylineLiveSlate:
    return MoneylineLiveSlate(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=200 + prediction_run_id,
        policy_version="1.0.0",
        target_date=TARGET_DATE,
        snapshot_role=snapshot_role,
        snapshot_started_at=STARTED_AT,
        run_type=run_type,
    )
