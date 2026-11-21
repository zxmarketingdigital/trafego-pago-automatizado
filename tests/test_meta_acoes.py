"""meta_acoes.py: pausar/ativar/orçamento com plano antes→depois e --confirmar.

Rede 100% stubada (FakeApi): nada chama a Meta. HOME temporário.

    python3 -m unittest tests/test_meta_acoes.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import tpa_paths  # noqa: E402
import meta_acoes  # noqa: E402

CONTA = "act_111111"
OUTRA = "999999"


class FakeApi(object):
    """Simula a Graph API. Campo inexistente no tipo devolve o erro real da Meta."""

    TIPOS = {
        "campanha": {"id", "name", "status", "effective_status", "account_id", "daily_budget",
                     "lifetime_budget", "objective"},
        "conjunto": {"id", "name", "status", "effective_status", "account_id", "daily_budget",
                     "lifetime_budget", "campaign_id", "optimization_goal"},
        "anuncio": {"id", "name", "status", "effective_status", "account_id", "campaign_id", "adset_id"},
    }

    def __init__(self, moeda="BRL"):
        self.moeda = moeda
        self.nos = {}
        self.posts = []
        self.recusar_post = False
        self.ignorar_post = False  # responde success mas não muda nada
        self.cair_depois = False   # aplica a mudança mas a resposta se perde (timeout)
        self.cair_sem_aplicar = False  # a conexão cai e nada é aplicado

    def add(self, nid, nivel, nome, status="ACTIVE", orc=None, conta="111111", effective=None):
        no = {"id": nid, "name": nome, "status": status, "effective_status": effective or status,
              "account_id": conta, "_nivel": nivel}
        if orc is not None:
            no["daily_budget"] = str(orc)
        self.nos[nid] = no

    def get(self, caminho, params=None):
        params = params or {}
        if caminho == CONTA:
            return {"name": "Conta Teste", "currency": self.moeda, "id": CONTA}
        if caminho.startswith(CONTA + "/") or caminho.split("/")[0] in self.nos and "/" in caminho:
            borda = caminho.split("/")[-1]
            nivel = {"campaigns": "campanha", "adsets": "conjunto", "ads": "anuncio"}[borda]
            itens = [{k: v for k, v in n.items() if not k.startswith("_")}
                     for n in self.nos.values() if n["_nivel"] == nivel]
            return {"data": itens}
        no = self.nos.get(caminho)
        if no is None:
            raise RuntimeError('Graph API 400: {"error":{"message":"Unsupported get request"}}')
        pedidos = set(params.get("fields", "").split(","))
        validos = self.TIPOS[no["_nivel"]]
        if pedidos - validos:
            raise RuntimeError('Graph API 400: {"error":{"message":"(#100) Tried accessing nonexisting field (%s)"}}'
                               % sorted(pedidos - validos)[0])
        return {k: v for k, v in no.items() if k in pedidos}

    def post(self, caminho, params, campo_arquivo=None, arquivo=None):
        self.posts.append((caminho, dict(params)))
        if self.recusar_post:
            raise RuntimeError('Graph API 400: {"error":{"message":"Invalid parameter"}}')
        if self.ignorar_post:
            return {"success": True}
        if self.cair_sem_aplicar:
            raise meta_acoes.SemResposta("Sem resposta da Meta: timed out")
        no = self.nos[caminho]
        for k, v in params.items():
            no[k] = v
            if k == "status":
                no["effective_status"] = v
        if self.cair_depois:
            raise meta_acoes.SemResposta("Sem resposta da Meta: timed out")
        return {"success": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tpa-acoes-"))
        env = {"OPERACAO_IA_HOME": str(self.tmp / "base")}
        self.paths = tpa_paths.active_paths(env=env, file=str(self.tmp / "nao-instalado" / "x.py"))
        self.api = FakeApi()
        self.api.add("120000000000001", "campanha", "Camp A", "ACTIVE")
        self.api.add("120000000000201", "conjunto", "Conj A", "ACTIVE", orc=5000)
        self.api.add("120000000000301", "anuncio", "Anuncio A", "ACTIVE")
        self.api.add("120000000000202", "conjunto", "Conj B", "PAUSED", orc=3000)
        self.api.add("120000000009001", "campanha", "Camp de outro cliente", "ACTIVE", conta=OUTRA)
        (self.paths.home / "config").mkdir(parents=True, exist_ok=True)
        self.paths.meta_env.write_text(
            "META_ACCESS_TOKEN=EAAtoken_secreto_123\nMETA_AD_ACCOUNT_ID=%s\n" % CONTA, encoding="utf-8")
        self.saida = []

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def out(self, texto=""):
        self.saida.append(str(texto))

    def rodar(self, *argv):
        self.saida = []
        codigo = meta_acoes.main(list(argv), api=self.api, paths=self.paths, out=self.out)
        return codigo, "\n".join(self.saida)

    def log(self):
        caminho = Path(self.paths.logs) / meta_acoes.LOG_NAME
        if not caminho.exists():
            return []
        return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestDryRunPadrao(Base):
    def test_pausar_sem_confirmar_nao_altera_nada(self):
        codigo, texto = self.rodar("pausar", "120000000000001")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [])
        self.assertEqual(self.api.nos["120000000000001"]["status"], "ACTIVE")
        self.assertIn("ATIVA → PAUSADA", texto)
        self.assertIn("--confirmar", texto)
        self.assertEqual(self.log(), [])

    def test_pausar_com_confirmar_aplica_verifica_e_registra(self):
        codigo, texto = self.rodar("pausar", "120000000000001", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [("120000000000001", {"status": "PAUSED"})])
        self.assertEqual(self.api.nos["120000000000001"]["status"], "PAUSED")
        self.assertIn("confirmado na Meta", texto)
        (linha,) = self.log()
        self.assertEqual((linha["acao"], linha["antes"], linha["depois"], linha["resultado"]),
                         ("status", "ACTIVE", "PAUSED", "ok"))
        self.assertTrue(linha["verificado"])
        self.assertEqual(linha["projeto"], self.paths.name)

    def test_ativar_conjunto_pausado(self):
        codigo, texto = self.rodar("ativar", "120000000000202", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.nos["120000000000202"]["status"], "ACTIVE")
        self.assertIn("Ativar começa a gastar", texto)

    def test_ja_esta_no_estado_pedido_nao_posta(self):
        codigo, texto = self.rodar("pausar", "120000000000202", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [])
        self.assertIn("Nada a alterar", texto)

    def test_varios_ids_na_mesma_chamada(self):
        codigo, _ = self.rodar("pausar", "120000000000001", "120000000000201", "120000000000301", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(len(self.api.posts), 3)
        self.assertEqual(len(self.log()), 3)

    def test_filho_com_pai_pausado_avisa(self):
        self.api.add("120000000000203", "conjunto", "Conj C", "PAUSED", orc=2000, effective="CAMPAIGN_PAUSED")
        _, texto = self.rodar("ativar", "120000000000203")
        self.assertIn("só entrega quando", texto)


class TestSegurancaDeConta(Base):
    def test_id_de_outra_conta_e_recusado(self):
        codigo, texto = self.rodar("pausar", "120000000009001", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.posts, [])
        self.assertIn("act_999999", texto)
        self.assertEqual(self.api.nos["120000000009001"]["status"], "ACTIVE")

    def test_um_id_invalido_no_lote_nao_aplica_nenhum(self):
        codigo, _ = self.rodar("pausar", "120000000000001", "120000000009001", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.posts, [])

    def test_id_nao_numerico_e_recusado(self):
        codigo, texto = self.rodar("pausar", "120000000000001; DROP", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("ID inválido", texto)
        self.assertEqual(self.api.posts, [])

    def test_token_nunca_aparece_na_saida(self):
        self.api.recusar_post = True
        _, texto = self.rodar("pausar", "120000000000001", "--confirmar")
        self.assertNotIn("EAAtoken_secreto_123", texto)

    def test_redige_mascara_token_e_bearer(self):
        bruto = "falhou Bearer EAAabc123 e access_token=EAAxyz e EAAtoken_secreto_123"
        limpo = meta_acoes.redige(bruto, "EAAtoken_secreto_123")
        for segredo in ("EAAabc123", "EAAxyz", "EAAtoken_secreto_123"):
            self.assertNotIn(segredo, limpo)


class TestOrcamento(Base):
    def test_plano_mostra_antes_depois_e_inteiro_enviado(self):
        codigo, texto = self.rodar("orcamento", "120000000000201", "80")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [])
        self.assertIn("R$ 50,00 → R$ 80,00", texto)
        self.assertIn("+60%", texto)
        self.assertIn("daily_budget=8000", texto)

    def test_confirmar_envia_centavos(self):
        codigo, _ = self.rodar("orcamento", "120000000000201", "80,50", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [("120000000000201", {"daily_budget": "8050"})])
        self.assertEqual(self.log()[0]["antes"], 5000)
        self.assertEqual(self.log()[0]["depois"], 8050)

    def test_moeda_sem_centavos_envia_unidade(self):
        self.api.moeda = "JPY"
        self.api.nos["120000000000201"]["daily_budget"] = "5000"
        self.rodar("orcamento", "120000000000201", "8000", "--confirmar")
        self.assertEqual(self.api.posts, [("120000000000201", {"daily_budget": "8000"})])

    def test_anuncio_nao_tem_orcamento(self):
        codigo, texto = self.rodar("orcamento", "120000000000301", "50", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.posts, [])
        self.assertIn("Anúncio não tem orçamento", texto)

    def test_campanha_cbo_sem_orcamento_diario_e_recusada(self):
        codigo, texto = self.rodar("orcamento", "120000000000001", "50", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.posts, [])
        self.assertIn("orçamento DIÁRIO", texto)

    def test_valor_zero_ou_negativo_ou_texto(self):
        for ruim in ("0", "abc", "-5"):
            codigo, _ = self.rodar("orcamento", "120000000000201", ruim, "--confirmar")
            self.assertEqual(codigo, 1, ruim)
        self.assertEqual(self.api.posts, [])

    def test_parse_valor(self):
        pv = meta_acoes.parse_valor
        self.assertEqual(str(pv("80")), "80")
        self.assertEqual(str(pv("80,5")), "80.5")
        self.assertEqual(str(pv("R$ 1.500,00")), "1500.00")
        self.assertEqual(str(pv("1,500.00")), "1500.00")
        self.assertEqual(str(pv("1.500.000")), "1500000")
        with self.assertRaises(meta_acoes.AcaoErro):
            pv("1.500")  # ambíguo: mil e quinhentos ou um e meio
        with self.assertRaises(meta_acoes.AcaoErro):
            pv("1,2,3")
        with self.assertRaises(meta_acoes.AcaoErro):
            pv("1.5,50")  # milhar mal formado
        self.assertEqual(str(pv("1.500,50")), "1500.50")

    def test_meta_recusou_registra_erro_e_sai_1(self):
        self.api.recusar_post = True
        codigo, texto = self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("recusou", texto)
        (linha,) = self.log()
        self.assertEqual(linha["resultado"], "erro")
        self.assertEqual(self.api.nos["120000000000201"]["daily_budget"], "5000")

    def test_sucesso_sem_efeito_nao_e_dado_como_confirmado(self):
        self.api.ignorar_post = True
        codigo, texto = self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertNotIn("confirmado na Meta", texto)
        self.assertFalse(self.log()[0]["verificado"])


class TestFalhaDeRedeDepoisDoEnvio(Base):
    def test_timeout_com_mudanca_aplicada_e_confirmada_lendo_de_volta(self):
        self.api.cair_depois = True
        codigo, texto = self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertIn("confirmado na Meta", texto)
        (linha,) = self.log()
        self.assertEqual(linha["resultado"], "ok")
        self.assertTrue(linha["verificado"])
        self.assertNotIn("Nada mudou", texto)

    def test_timeout_com_valor_anterior_nao_afirma_que_nada_mudou(self):
        self.api.cair_sem_aplicar = True
        codigo, texto = self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("pode aplicar com atraso", texto)
        self.assertNotIn("nada mudou", texto.lower())
        self.assertEqual(self.log()[0]["resultado"], "incerto")

    def test_timeout_e_leitura_falha_fica_incerto_sem_afirmar_nada(self):
        self.api.cair_depois = True
        original = self.api.get

        # busca_entidade usa get com campos; deixa a primeira leitura passar
        chamadas = {"n": 0}

        def get_uma_vez(caminho, params=None):
            if caminho == "120000000000201":
                chamadas["n"] += 1
                if chamadas["n"] > 2:  # depois da detecção de nível e do plano
                    raise RuntimeError("Sem resposta da Meta")
            return original(caminho, params)

        self.api.get = get_uma_vez
        codigo, texto = self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("PODE ter sido aplicada", texto)
        self.assertNotIn("Nada mudou", texto)
        self.assertEqual(self.log()[0]["resultado"], "incerto")


class TestPostRealSemRede(Base):
    """GraphApi.post com urlopen simulado: classifica o que é 'recusa' e o que é 'incerto'."""

    def _post_com(self, excecao):
        from unittest import mock
        api = meta_acoes.GraphApi("EAAtoken_secreto_123")
        with mock.patch.object(meta_acoes, "urlopen", side_effect=excecao):
            api.post("120000000000201", {"status": "PAUSED"})

    def test_5xx_e_incerto(self):
        import io
        from urllib.error import HTTPError
        with self.assertRaises(meta_acoes.SemResposta):
            self._post_com(HTTPError("u", 503, "x", {}, io.BytesIO(b"{}")))

    def test_4xx_e_recusa_definitiva(self):
        import io
        from urllib.error import HTTPError
        with self.assertRaises(RuntimeError) as cm:
            self._post_com(HTTPError("u", 400, "x", {}, io.BytesIO(b"{}")))
        self.assertNotIsInstance(cm.exception, meta_acoes.SemResposta)

    def test_incomplete_read_e_json_invalido_viram_incerto(self):
        import http.client
        with self.assertRaises(meta_acoes.SemResposta):
            self._post_com(http.client.IncompleteRead(b"x"))
        with self.assertRaises(meta_acoes.SemResposta):
            self._post_com(ValueError("json"))


class TestGetEJsonDoLog(Base):
    def test_get_com_erro_de_rede_vira_runtimeerror(self):
        from unittest import mock
        import http.client
        api = meta_acoes.GraphApi("EAAtoken_secreto_123")
        fm = meta_acoes._fm()
        for exc in (OSError("reset"), http.client.IncompleteRead(b"x"), ValueError("json")):
            with mock.patch.object(fm, "graph_get", side_effect=exc):
                with self.assertRaises(RuntimeError):
                    api.get("120000000000201", {})

    def test_escrita_interrompida_no_log_nao_cola_na_proxima_mudanca(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        caminho = Path(self.paths.logs) / meta_acoes.LOG_NAME
        with caminho.open("a", encoding="utf-8") as fh:
            fh.write('{"mudanca": "quebrad')  # fragmento sem quebra de linha
        self.rodar("pausar", "120000000000201", "--confirmar")
        validas = []
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            try:
                validas.append(json.loads(linha).get("entidade_id"))
            except ValueError:
                pass
        self.assertEqual(validas, ["120000000000001", "120000000000201"])


class TestOutrosBordas(Base):
    def test_corpo_de_erro_que_se_perde_vira_incerto(self):
        from unittest import mock
        from urllib.error import HTTPError
        import http.client

        class Corpo(object):
            def read(self):
                raise http.client.IncompleteRead(b"x")

        api = meta_acoes.GraphApi("EAAtoken_secreto_123")
        erro = HTTPError("u", 500, "x", {}, Corpo())
        with mock.patch.object(meta_acoes, "urlopen", side_effect=erro):
            with self.assertRaises(meta_acoes.SemResposta):
                api.post("120000000000201", {"status": "PAUSED"})

    def test_token_do_ambiente_do_shell_nao_vale(self):
        from unittest import mock
        self.paths.meta_env.write_text("META_AD_ACCOUNT_ID=%s\n" % CONTA, encoding="utf-8")
        with mock.patch.dict(os.environ, {"META_ACCESS_TOKEN": "EAAdeoutrocliente"}):
            with self.assertRaises(meta_acoes.AcaoErro):
                meta_acoes.montar_contexto(api=None, paths=self.paths)

    def test_listar_status_pausado_inclui_pausado_pelo_pai(self):
        self.api.add("120000000000203", "conjunto", "Conj C", "ACTIVE", orc=1000, effective="CAMPAIGN_PAUSED")
        _, texto = self.rodar("listar", "--nivel", "conjunto", "--status", "PAUSED")
        self.assertIn("120000000000203", texto)


class TestLogComFalha(Base):
    def test_log_que_nao_grava_nao_derruba_o_lote_e_imprime_o_registro(self):
        orig = meta_acoes.registrar

        def quebrado(ctx, entrada):
            raise PermissionError("somente leitura")

        meta_acoes.registrar = quebrado
        try:
            codigo, texto = self.rodar("pausar", "120000000000001", "120000000000201", "--confirmar")
        finally:
            meta_acoes.registrar = orig
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.nos["120000000000001"]["status"], "PAUSED")
        self.assertEqual(self.api.nos["120000000000201"]["status"], "PAUSED")  # o lote continuou
        self.assertIn("Guarde esta linha", texto)
        self.assertNotIn("EAAtoken", texto)


class TestListarEDesfazerBordas(Base):
    def test_listar_campanha_de_outra_conta_e_recusado(self):
        codigo, texto = self.rodar("listar", "--nivel", "conjunto", "--campanha", "120000000009001")
        self.assertEqual(codigo, 1)
        self.assertIn("pertence à conta", texto)

    def test_desfazer_orcamento_sem_orcamento_diario_atual_da_mensagem(self):
        self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        mudanca = self.log()[0]["mudanca"]
        del self.api.nos["120000000000201"]["daily_budget"]  # virou CBO
        codigo, texto = self.rodar("desfazer", mudanca)
        self.assertEqual(codigo, 1)
        self.assertIn("não tem mais orçamento diário", texto)
        self.assertNotIn("Traceback", texto)


class TestLogBytesEDesfazerVerificado(Base):
    def test_ler_log_ignora_bytes_utf8_quebrados_sem_derrubar(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        with open(self.ctx_log_path(), "ab") as f:
            f.write(b"\xff\xfe lixo\n")
        _, texto = self.rodar("historico")
        self.assertIn("120000000000001", texto)

    def ctx_log_path(self):
        return next(self.tmp.rglob("meta-acoes.jsonl"))

    def test_desfazer_nao_verificado_nao_conta_como_desfeito(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        mudanca = self.log()[0]["mudanca"]
        self.rodar("desfazer", mudanca, "--confirmar")
        caminho = self.ctx_log_path()
        linhas = [json.loads(x) for x in caminho.read_text(encoding="utf-8").splitlines() if x.strip()]
        for item in linhas:
            if item.get("desfaz") == mudanca:
                item["verificado"] = False
        caminho.write_text("\n".join(json.dumps(i) for i in linhas) + "\n", encoding="utf-8")
        codigo, texto = self.rodar("desfazer", mudanca)
        self.assertEqual(codigo, 0)
        self.assertNotIn("já foi desfeita", texto)


class TestCtrlCNaConferencia(Base):
    def test_ctrl_c_na_leitura_de_volta_registra_incerto(self):
        original = self.api.get

        def get(caminho, params=None):
            if caminho == "120000000000001" and getattr(self, "_pos", False):
                raise KeyboardInterrupt()
            return original(caminho, params)

        post_orig = self.api.post

        def post(caminho, params, *a, **k):
            r = post_orig(caminho, params, *a, **k)
            self._pos = True
            return r

        self.api.get, self.api.post = get, post
        with self.assertRaises(KeyboardInterrupt):
            self.rodar("pausar", "120000000000001", "--confirmar")
        self.assertEqual(self.log()[-1]["resultado"], "incerto")


class TestHistoricoEDesfazer(Base):
    def test_historico_lista_ultimas_mudancas(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        _, texto = self.rodar("historico")
        self.assertIn("120000000000001", texto)
        self.assertIn("ATIVA → PAUSADA", texto)

    def test_desfazer_status(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        mudanca = self.log()[0]["mudanca"]
        codigo, texto = self.rodar("desfazer", mudanca)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.nos["120000000000001"]["status"], "PAUSED")  # só plano
        self.assertIn("PAUSADA → ATIVA", texto)
        codigo, _ = self.rodar("desfazer", mudanca, "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.nos["120000000000001"]["status"], "ACTIVE")
        self.assertEqual(self.log()[-1]["desfaz"], mudanca)

    def test_desfazer_orcamento_ultima(self):
        self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.rodar("desfazer", "--ultima", "--confirmar")
        self.assertEqual(self.api.nos["120000000000201"]["daily_budget"], "5000")

    def test_nao_desfaz_duas_vezes(self):
        self.rodar("pausar", "120000000000001", "--confirmar")
        mudanca = self.log()[0]["mudanca"]
        self.rodar("desfazer", mudanca, "--confirmar")
        codigo, texto = self.rodar("desfazer", mudanca, "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("já foi desfeita", texto)

    def test_desfazer_avisa_quando_alguem_mexeu_depois(self):
        self.rodar("orcamento", "120000000000201", "80", "--confirmar")
        self.api.nos["120000000000201"]["daily_budget"] = "9999"
        _, texto = self.rodar("desfazer", "--ultima")
        self.assertIn("alguém mexeu depois", texto)

    def test_desfazer_id_inexistente(self):
        codigo, texto = self.rodar("desfazer", "zzzz9999", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("Não achei a mudança", texto)


class TestMultiProjeto(Base):
    def test_log_vai_para_a_pasta_do_projeto_ativo(self):
        tpa_paths.create_project("cliente-x", self.tmp / "base", activate=False, port_free=lambda p: True)
        env = {"OPERACAO_IA_HOME": str(self.tmp / "base"), "TPA_PROJECT": "cliente-x"}
        proj = tpa_paths.active_paths(env=env, file=str(self.tmp / "nao-instalado" / "x.py"))
        self.assertNotEqual(str(proj.logs), str(self.paths.logs))
        (proj.home / "config").mkdir(parents=True, exist_ok=True)
        proj.meta_env.write_text("META_ACCESS_TOKEN=tok\nMETA_AD_ACCOUNT_ID=%s\n" % CONTA, encoding="utf-8")
        saida = []
        meta_acoes.main(["pausar", "120000000000001", "--confirmar"], api=self.api, paths=proj, out=saida.append)
        self.assertTrue((Path(proj.logs) / meta_acoes.LOG_NAME).exists())
        self.assertFalse((Path(self.paths.logs) / meta_acoes.LOG_NAME).exists())
        self.assertIn("cliente-x", "\n".join(saida))

    def test_projeto_sem_conta_recusa(self):
        self.paths.meta_env.write_text("META_ACCESS_TOKEN=tok\n", encoding="utf-8")
        codigo, texto = self.rodar("pausar", "120000000000001", "--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("Sem conta de anúncios", texto)
        self.assertEqual(self.api.posts, [])


class TestListar(Base):
    def test_listar_campanhas_mostra_id_status_e_nome(self):
        codigo, texto = self.rodar("listar")
        self.assertEqual(codigo, 0)
        self.assertIn("120000000000001", texto)
        self.assertIn("Camp A", texto)

    def test_listar_conjuntos_mostra_orcamento_e_filtra_status(self):
        _, texto = self.rodar("listar", "--nivel", "conjunto", "--status", "PAUSED")
        self.assertIn("120000000000202", texto)
        self.assertNotIn("120000000000201", texto)
        self.assertIn("R$ 30,00", texto)


class TestTextoDoAluno(unittest.TestCase):
    def test_fonte_nao_cita_colaborador_nem_so_mac(self):
        texto = (REPO / "scripts" / "meta_acoes.py").read_text(encoding="utf-8").lower()
        for proibido in ("seu mac",):
            self.assertNotIn(proibido, texto)


if __name__ == "__main__":
    unittest.main()
