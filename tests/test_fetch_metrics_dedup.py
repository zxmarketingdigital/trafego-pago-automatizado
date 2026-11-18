import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_metrics as fm  # noqa: E402


def test_variantes_do_mesmo_evento_nao_somam():
    actions = [
        {"action_type": "purchase", "value": "3"},
        {"action_type": "omni_purchase", "value": "3"},
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
    ]
    assert fm.get_action_count(actions, fm.ACTION_TYPES["purchases"]) == 3.0


def test_mensagens_contam_so_conversas_iniciadas():
    actions = [
        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "18"},
        {"action_type": "onsite_conversion.messaging_first_reply", "value": "14"},
    ]
    assert fm.get_action_count(actions, fm.ACTION_TYPES["messages"]) == 18.0


def test_valor_invalido_e_lista_vazia():
    assert fm.get_action_count([], fm.ACTION_TYPES["leads"]) == 0.0
    assert fm.get_action_count([{"action_type": "lead", "value": "x"}], fm.ACTION_TYPES["leads"]) == 0.0


def test_leads_formulario_e_pixel_sem_agregado_somam():
    actions = [
        {"action_type": "onsite_conversion.lead_grouped", "value": "25"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "40"},
    ]
    assert fm.get_action_count(actions, fm.ACTION_TYPES["leads"], fm.DISJOINT_PARTS["leads"]) == 65.0


def test_leads_com_agregado_nao_conta_em_dobro():
    actions = [
        {"action_type": "lead", "value": "65"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "25"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "40"},
        {"action_type": "leadgen.other", "value": "25"},
    ]
    assert fm.get_action_count(actions, fm.ACTION_TYPES["leads"], fm.DISJOINT_PARTS["leads"]) == 65.0
