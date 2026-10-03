# Shared implementation contract

Implementation v0.1.0 alpha, standalone Django 5.2, uv. No claim that all external connectors are verified. Python app `reportbuilder`, config `config`.

Canonical definition:
```
{schema_version:'1.0.0', name:'Report', parameters:[], datasets:[
 {dataset_id:'ds1',alias:'data',cardinality:'many',objects:[{object_id:'obj1',alias:'rows'}],
 fields:[{field_id:'f1',object_id:'obj1',alias:'name',label:'Name',type:'string',required:true,nullable:true}],
 query:{projection:['f1'],filters:{op:'and',items:[]},sorts:[],groups:[],aggregates:[]}}
],pages:[{page_id:'p1',kind:'flow',width_mm:210,height_mm:297,
 margins:{top:15,right:15,bottom:15,left:15},dataset_id:'ds1',elements:[],bands:[
 {band_id:'b1',type:'ReportHeader',height_mm:15,elements:[]},
 {band_id:'b2',type:'Detail',height_mm:8,elements:[{element_id:'e1',type:'field',
 geometry:{x_mm:0,y_mm:0,width_mm:80,height_mm:7},
 binding:{dataset_id:'ds1',field_id:'f1',scope:'row'},
 style:{font_size_pt:10,text_align:'left'},overflow:'fixed_clip'}]}
]}]}
```
Element types: text, field, image, line, rectangle, page_number, total_pages, parameter, generated_at, page_break. Text uses `text`; images use `asset_id` UUID; parameter uses `parameter_name`. Parent implicit in arrays. Position origin is printable area or band. Backend validates fixed_clip/grow (unsupported must explicitly reject).

Local binding: `{dataset_id,connection_id,object_mappings:{obj1:{schema:null,object:'employees'}},field_mappings:{f1:{column:'name',conversion:'identity'}}}`. IDs stable; never put physical names/secrets in definition. Query filter leaf `{field_id,operator:'eq',value:'abc'}` or `{field_id,operator:'gte',parameter:'start'}`; AND/OR node op/items. sorts field_id/direction/nulls.

Data module public API: `connector_catalog()`, `introspect(kind,config)`, `test_connection(kind,config)`, `execute_dataset(kind,config,contract,binding,parameters=None,max_rows=10000)` returns `{fields:[...],rows:[{field_id:JSON-safe value}],row_count,...}`. Root supplies config with uploaded file resolved path and decrypted secrets. Raise `DataError(code,message)` safe errors. SQLite arbitrary path only admin-created connection with upload.

Definition/layout API: `default_definition(name='새 보고서')`, `validate_definition(definition)` raises `DefinitionError`, `render_report(definition,datasets,parameters=None,asset_resolver=None)` returns `{html:str,page_count:int,pages:[str],...}`. datasets dict dataset_id to data result. asset_resolver(asset_id) returns approved data URL. `pdf_bytes(html)` optional Playwright. Packaging API `export_project(name,reports,assets=None)` report list [{name,definition}], assets {asset_id:{content:bytes,filename,mime}} returns bytes; `import_project(bytes)` validates and returns {name,reports,assets}. JSON shape match maintained.

UI API `/api/connections/` GET/POST, `/api/connections/<uuid>/test/` POST, `/api/connections/<uuid>/schema/` GET; `/api/reports/` GET/POST; `/api/reports/<uuid>/` GET/PUT with body {name,definition,expected_revision}; GET report response {id,name,definition,revision,bindings:[...],published_revision}. `/api/reports/<uuid>/bindings/` PUT body {bindings:[...]}; `/api/reports/<uuid>/preview/` POST {parameters:{}} => {html,page_count}; `/api/reports/<uuid>/publish/` POST => publication_url; `/reports/<uuid>/export/<format>/` GET; `/api/assets/` POST multipart image => {id,url}; `/projects/import/` POST multipart project; `/reports/<uuid>/export/project/` GET. CSRF cookie required, DOM textContent for untrusted data.

Root owns Django models/views/urls/settings/auth, templates base/dashboard/connections/library/viewer, docs/deploy/CI. UI agent owns designer template, static designer JS and site CSS. Data agent owns data module+tests. Layout agent owns definition, rendering, packaging+tests+schemas. Communicate changed interfaces before writing.
