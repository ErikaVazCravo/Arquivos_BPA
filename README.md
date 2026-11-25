# Editor BPA web

Aplicação Streamlit para consultar e editar registros BPA-I e BPA-C e o cabeçalho de arquivos BPA. Usa os layouts e o cálculo de controle do `Editor_BPA_COMPLETO_CNES.py`.

## Executar

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Selecione um arquivo de qualquer extensão, consulte pelo tipo, CNES, folha e sequência e aplique as alterações. Baixe a cópia atualizada pela barra lateral. O arquivo original não é modificado. O aplicativo mantém os dados na sessão enquanto ela estiver ativa; baixe o arquivo antes de encerrar ou recarregar a sessão. Não inclui nem exclui registros.

Os campos de controle do cabeçalho são recalculados ao aplicar uma edição. A aplicação valida a chave do registro e algumas regras de preenchimento, mas não substitui a validação completa pelo BPA/SIA.
