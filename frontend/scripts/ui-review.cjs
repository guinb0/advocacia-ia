// Revisão visual com dados fictícios; todas as chamadas /api são interceptadas.
// CSP ignorada somente neste contexto de teste para permitir fixtures no host local.
// PLAYWRIGHT_PATH pode apontar para uma instalação temporária, sem alterar dependências.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const out = require('node:path').join(require('node:os').tmpdir(), 'forense-ui-review');
fs.mkdirSync(out, {recursive:true});
const base = process.env.UI_REVIEW_URL || 'http://127.0.0.1:3100';
let browser;
(async()=>{
browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({bypassCSP:true,viewport:{width:1440,height:1000}});
const page=await context.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
const casos=[{id:'caso-teste-01',cliente:'Márcia Oliveira',categoria:'trabalhista',observacao:'',telefone:'',criado_em:'2026-09-10T12:00:00',atualizado_em:'2026-09-10T12:00:00',total_entregas:3}];
// A central de Documentação é um painel de plantão: o teste precisa separar
// "servidor ainda não respondeu" de "respondeu e a fila está vazia". Este
// interruptor deixa a fixture cair de propósito para cobrir o primeiro caso.
let documentacaoIndisponivel=true;
const agora=()=>new Date().toISOString();
const filaDocumentacao=()=>({entrevistas_ativas:2,solicitacoes:1,documentadores_online:3,arquivos_recebidos:12,pendencias_obrigatorias:4,itens_a_conferir:2,casos_prontos:1,atendimentos:[
{entrevista_id:'ent-01',caso_id:'caso-teste-01',cliente:'Márcia Oliveira',sala:'sala-01',status:'solicitado',entrevistador_nome:'Ana Prado',documentador_nome:null,iniciado_em:agora(),solicitado_em:agora(),atualizado_em:agora(),documentos:{categoria:'Trabalhista',arquivos_recebidos:5,obrigatorios_total:3,obrigatorios_entregues:2,percentual:66,pendencias:['Carteira de trabalho'],a_conferir:['Holerite de março'],processando:1,em_triagem:2,pronto:false,ultima_entrega_em:agora()}},
{entrevista_id:'ent-02',caso_id:null,cliente:'',sala:null,status:'entrevista',entrevistador_nome:'Bruno Dias',documentador_nome:null,iniciado_em:agora(),solicitado_em:null,atualizado_em:agora(),documentos:null}]});
await context.route('**/api/**',async route=>{
const path=new URL(route.request().url()).pathname;
let data;let status=200;
if(path==='/api/user/my-account')data={flag:true,data:{codigo:'ui-test',nome:'Revisão visual',perfil:'administrador',email:'teste@example.test',senhaPadrao:false,modulos:['casos','documentos','usuarios','metricas','operacao','entrevista','supervisao','agente','revisao','documentacao','roteiros','contratos','glossario_documentos']}};
else if(path==='/api/casos')data={casos};
else if(path==='/api/categorias')data={categorias:[{codigo:'trabalhista',nome:'Trabalhista',descricao:'Documentos para análise do vínculo de trabalho.',total_documentos:5,total_obrigatorios:3,itens:[]}]};
else if(path==='/api/carteira')data={situacoes:[],total:0,pagina:1,tamanho:10,paginas:1,triagem:{travados:0,aConferir:0,pedidosProntos:0,completos:0,ativos:0},chegando_agora:[],pedidos:[],categorias:[]};
else if(path==='/api/documentacao/presenca')data={};
else if(path==='/api/documentacao/atendimentos'){if(documentacaoIndisponivel){status=503;data={detail:'Serviço de documentação indisponível'};}else data=filaDocumentacao();}
else {status=503;data={detail:'API simulada indisponível na revisão visual'};}
await route.fulfill({status,headers:{'Access-Control-Allow-Origin':new URL(base).origin,'Access-Control-Allow-Credentials':'true'},contentType:'application/json',body:JSON.stringify(data)});
});
await page.goto(base + '/home');await page.getByRole('button',{name:'Casos e clientes',exact:true}).waitFor();
await page.screenshot({path:out+'/dashboard.png',fullPage:true});
await page.getByRole('button',{name:'Casos e clientes',exact:true}).click();
await page.getByLabel('Buscar casos',{exact:true}).fill('impossivel');
await page.getByText('Nenhum caso corresponde aos filtros.',{exact:false}).waitFor();
await page.getByRole('button',{name:'Limpar filtros',exact:true}).click();
await page.getByText('Márcia Oliveira',{exact:true}).waitFor();
await page.getByLabel('Buscar casos',{exact:true}).fill('marcia');
await page.getByText('Márcia Oliveira',{exact:true}).waitFor();
await page.screenshot({path:out+'/casos.png',fullPage:true});
await page.getByRole('button',{name:'Usar tema escuro',exact:true}).click();
assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'dark');
await page.waitForTimeout(200);
await page.screenshot({path:out+'/casos-dark.png',fullPage:true});
await page.getByRole('button',{name:'Usar tema claro',exact:true}).click();

// --- Central de Documentação: falha inicial, recuperação e fila -----------
await page.getByRole('navigation',{name:'Módulos do sistema'}).getByRole('button',{name:'Documentos',exact:true}).click();
await page.getByRole('heading',{name:'Departamento de Documentação',exact:true}).waitFor();
await page.getByText('A central ainda não recebeu dados do servidor',{exact:false}).waitFor();
// Sem resposta do servidor, nenhum número pode estar na tela: um "0" aqui
// seria lido como "não tem ninguém esperando".
const semDados=await page.getByRole('region',{name:'Resumo da operação'}).count();
assert.equal(semDados,0,'O resumo não pode aparecer antes da primeira resposta');
await page.screenshot({path:out+'/documentacao-sem-dados.png',fullPage:true});
documentacaoIndisponivel=false;
await page.getByRole('button',{name:'Tentar agora',exact:true}).click();
await page.getByRole('region',{name:'Resumo da operação'}).waitFor();
await page.getByText('Márcia Oliveira',{exact:true}).first().waitFor();
await page.getByRole('button',{name:/^Chamando equipe/}).click();
await page.getByText('Márcia Oliveira',{exact:true}).first().waitFor();
assert.equal(await page.getByText('Bruno Dias',{exact:false}).count(),0,'O filtro deve esconder quem não chamou a equipe');
await page.getByRole('button',{name:/^Todos/}).click();
await page.getByText('Bruno Dias',{exact:false}).first().waitFor();
await page.screenshot({path:out+'/documentacao.png',fullPage:true});

// --- Modulos migrados para CabecalhoPagina -------------------------------
// Sem fixture: a API responde 503 de proposito. O que se verifica aqui e que o
// cabecalho da pagina existe, tem um h1 so, e que a tela nao quebra no erro.
for(const [modulo,titulo] of [['Investigação','Investigação do caso'],['Supervisão','Supervisão'],['Administração','Administração de acessos'],['Saúde do agente','Saúde do agente jurídico'],['Operação','Operação da equipe'],['Acompanhamento','Documentos pendentes'],['Roteiros','Roteiros de entrevista'],['Glossário de documentos','Glossário de documentos'],['Dados','Dados do acervo']]){
await page.getByRole('navigation',{name:'Módulos do sistema'}).getByRole('button',{name:modulo,exact:true}).click();
await page.getByRole('heading',{name:titulo,exact:true,level:1}).waitFor();
assert.equal(await page.getByRole('heading',{level:1}).count(),1,`${modulo} deve ter exatamente um h1`);
}
await page.mouse.move(760,12);
await page.screenshot({path:out+'/modulo-supervisao.png',fullPage:true});

// --- Entrevista guiada: o modulo passou a ter h1 proprio -----------------
await page.getByRole('navigation',{name:'Módulos do sistema'}).getByRole('button',{name:'Entrevista guiada',exact:true}).click();
await page.getByRole('heading',{name:'Entrevista guiada',exact:true,level:1}).waitFor();
await page.getByText('Como você quer começar?',{exact:false}).waitFor();
// Tira o ponteiro de cima do item clicado: hover e atual nao podem se confundir
// no retrato, e so um modulo pode estar marcado como atual.
await page.mouse.move(760,12);
const modulosAtuais=await page.getByRole('navigation',{name:'Módulos do sistema'}).locator('[aria-current="page"]').count();
assert.equal(modulosAtuais,1,'Só um módulo pode aparecer como atual');
await page.screenshot({path:out+'/entrevista.png',fullPage:true});

await page.getByRole('navigation',{name:'Módulos do sistema'}).getByRole('button',{name:'Casos e clientes',exact:true}).click();
await page.getByLabel('Buscar casos',{exact:true}).waitFor();

await page.getByLabel('Buscar módulo',{exact:true}).fill('peticao');
await page.getByRole('button',{name:'Modelos de petição',exact:true}).waitFor();
assert.equal(await page.getByRole('navigation',{name:'Módulos do sistema'}).getByRole('button',{name:'Documentos',exact:true}).count(),0);
await page.getByRole('button',{name:'Limpar busca de módulos',exact:true}).click();
const reports=[];
for(const width of [1440,1024,768,390]){
await page.setViewportSize({width,height:900});
reports.push({width,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
}
// No celular a lista de casos precisa aparecer antes do cadastro: o formulario
// comeca fechado e so abre por pedido explicito, que leva o foco ao 1o campo.
assert.equal(await page.getByLabel('Nome do cliente',{exact:true}).isVisible(),false,'O cadastro deve comecar fechado no celular');
await page.getByText('Márcia Oliveira',{exact:true}).first().waitFor();
await page.screenshot({path:out+'/casos-mobile.png',fullPage:true});
await page.getByRole('button',{name:'Novo caso',exact:true}).click();
await page.getByLabel('Nome do cliente',{exact:true}).waitFor();
const focoNoCadastro=await page.getByLabel('Nome do cliente',{exact:true}).evaluate(el=>el===document.activeElement);
assert.equal(focoNoCadastro,true,'Abrir o cadastro deve levar o foco ao primeiro campo');
await page.getByRole('button',{name:'Fechar cadastro',exact:true}).click();
assert.equal(await page.getByLabel('Nome do cliente',{exact:true}).isVisible(),false,'Fechar o cadastro devolve a lista ao topo');
await page.getByRole('button',{name:/Abrir.*menu|Abrir navega/i}).click();
await page.getByRole('dialog').getByRole('button',{name:'Fechar menu',exact:true}).waitFor();
const dialog=page.getByRole('dialog');const focusInside=await dialog.evaluate(el=>el.contains(document.activeElement));
await page.keyboard.press('Shift+Tab');const trap=await dialog.evaluate(el=>el.contains(document.activeElement));
await page.keyboard.press('Escape');
await page.screenshot({path:out+'/mobile.png',fullPage:true});
// A central também precisa caber no celular do plantonista.
await page.getByRole('button',{name:/Abrir.*menu|Abrir navega/i}).click();
await page.getByRole('dialog').getByRole('button',{name:'Documentos',exact:true}).click();
await page.getByRole('heading',{name:'Departamento de Documentação',exact:true}).waitFor();
reports.push({width:390,contexto:'documentacao',overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
await page.screenshot({path:out+'/documentacao-mobile.png',fullPage:true});
assert(reports.every(r=>!r.overflow), 'A página não deve transbordar');
assert(focusInside && trap, 'A gaveta deve conter o foco');
assert.deepEqual(errors, [], 'Não deve haver erros de execução');
await page.getByRole('button',{name:'Usar tema escuro',exact:true}).click();
await page.setViewportSize({width:1440,height:1000});
await page.getByRole('button',{name:'Usar tema claro',exact:true}).waitFor();
await page.waitForTimeout(400);// deixa a transicao de cor terminar antes do retrato
await page.screenshot({path:out+'/documentacao-dark.png',fullPage:true});
await page.reload();
assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'dark');
console.log(JSON.stringify({reports,focusInside,trap,errors,filters:'passed',theme:'passed',moduleSearch:'passed',documentacao:'passed',casosMobile:'passed',entrevista:'passed',modulos:'passed'},null,2));
await browser.close();
})().catch(async e=>{console.error(e);await browser?.close();process.exitCode=1;});
