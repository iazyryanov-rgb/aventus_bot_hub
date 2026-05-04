# CO · Credito365 CRM DB — справочник таблиц

База: `prod_credito365_api` · сервер: `localhost:55610` · пользователь: `viewer` (только чтение).
Снапшот схемы: 2026-05-04. Полный дамп — рядом в [CO_credito365_schema.json](CO_credito365_schema.json) (255 таблиц, столбцы, FK).

**Всего таблиц:** 255.  **Префиксов:** 85.  **Движок:** в основном InnoDB.

## Топ-25 таблиц по числу строк

| Таблица | Строк | Колонок |
|---|---:|---:|
| `payment_operation` | 113,196,240 | 8 |
| `payment_details` | 104,879,964 | 4 |
| `revisions` | 38,358,178 | 3 |
| `loan_audit` | 28,077,009 | 50 |
| `user_event` | 27,399,103 | 9 |
| `sms` | 17,427,089 | 13 |
| `loan_transaction` | 11,871,339 | 8 |
| `loan_calculation_plan` | 10,669,318 | 7 |
| `user_audit` | 8,203,924 | 43 |
| `loan_transition_history` | 4,298,681 | 11 |
| `payment_transaction` | 3,761,872 | 26 |
| `user_note_audit` | 2,997,350 | 10 |
| `user_visits` | 2,939,498 | 5 |
| `call_base_transfer_history` | 2,743,955 | 5 |
| `email` | 2,607,744 | 18 |
| `user_device_info` | 2,579,594 | 22 |
| `user_note` | 2,407,022 | 8 |
| `communication_history_item` | 2,356,602 | 6 |
| `journey_map_event` | 1,992,664 | 7 |
| `druo_collect_money` | 1,940,208 | 17 |
| `api` | 1,883,793 | 11 |
| `loan_note_audit` | 1,841,673 | 10 |
| `webitel_call` | 1,637,221 | 27 |
| `loan_note` | 1,625,681 | 8 |
| `cobre_collect_money` | 1,385,196 | 16 |

## Категории (по префиксу имени)

| Префикс | Таблиц | ~Строк | Что внутри (примеры) |
|---|---:|---:|---|
| **loan** | 24 | 64,099,217 | `loan_audit`, `loan_transaction`, `loan_calculation_plan`, `loan_transition_history` |
| **user** | 24 | 57,334,840 | `user_event`, `user_audit`, `user_note_audit`, `user_visits` |
| **postman** | 10 | 25,351 | `postman_email`, `postman_email_attachment`, `postman_legal_petition_radicado`, `postman_email_category` |
| **collection** | 8 | 1,807,989 | `collection_call`, `collection_call_message`, `collection_result_promise_to_pay`, `collection_agency_report` |
| **ai** | 7 | 148 | `ai_report`, `ai_prompt_template_admin`, `ai_prompt_template`, `ai_report_schedule_manager` |
| **call** | 7 | 2,750,154 | `call_base_transfer_history`, `call_center_campaign_run`, `call_center_audience`, `call_center_call_base` |
| **payment** | 7 | 222,057,197 | `payment_operation`, `payment_details`, `payment_transaction`, `payment_registry` |
| **collector** | 6 | 1,088,359 | `collector_notification`, `collector_assignment_history`, `collector_target`, `collector_category_assignment` |
| **aws** | 5 | 1,636,143 | `aws_face_rekognition`, `aws_face_rekognition_match`, `aws_face_compare_match`, `aws_face_compare` |
| **journey** | 5 | 2,311,874 | `journey_map_event`, `journey_map_user_tag`, `journey_map_application`, `journey_map_loan` |
| **siigo** | 5 | 2,849 | `siigo_customer`, `siigo_invoice_item`, `siigo_invoice`, `siigo_fetched_invoice` |
| **affiliate** | 4 | 914,955 | `affiliate_event`, `affiliate_log`, `affiliate_action`, `affiliate` |
| **auto** | 4 | 261 | `auto_debit_campaign`, `auto_debit_strategy_banks`, `auto_debit_strategy_step`, `auto_debit_strategy` |
| **cobre** | 4 | 1,825,514 | `cobre_collect_money`, `cobre_transfer_money`, `cobre_direct_debit_registration`, `cobre_counterparty` |
| **druo** | 4 | 2,102,529 | `druo_collect_money`, `druo_connect_account`, `druo_end_user`, `druo_transfer_money` |
| **duplicate** | 4 | 197,076 | `duplicate_registration`, `duplicate_user_log`, `duplicate_user_photo_log`, `duplicate_registration_attempt` |
| **report** | 4 | 5,914 | `report_task`, `report_task_file`, `report_result`, `report` |
| **sls** | 4 | 406,810 | `sls_application_response`, `sls_application`, `sls_application_attempt`, `sls_application_enrich_data` |
| **threshold** | 4 | 98 | `threshold_inactive_staff_alert`, `threshold_alert_rule_recipient`, `threshold_alert_rule`, `threshold_alert_log` |
| **ab** | 3 | 35,154 | `ab_allocation`, `ab_experiment`, `ab_experiment_event` |
| **action** | 3 | 926 | `action_tree`, `action_tree_catalog_item`, `action_tree_catalog_group` |
| **default** | 3 | 207 | `default_amount_matrix_repeated`, `default_amount_matrix_new`, `default_amount_fallback` |
| **discount** | 3 | 8,154 | `discount_code`, `discount`, `discount_condition` |
| **file** | 3 | 1,606,919 | `file`, `file_request`, `file_matches` |
| **ms** | 3 | 196 | `ms_teams_outgoing_jira_link`, `ms_teams_processed_activity`, `ms_teams_conversation_link` |
| **peerberry** | 3 | 102,800 | `peerberry_process_result`, `peerberry_process`, `peerberry_setting` |
| **price** | 3 | 18 | `price_element`, `price_setting`, `price_matrix` |
| **template** | 3 | 430 | `template_sms`, `template_email`, `template_web` |
| **tmp** | 3 | 27 | `tmp_ai_report_schedule_manager_backup_20260425`, `tmp_ai_report_schedule_target_admin_backup_20260425`, `tmp_ai_report_schedule_backup_20260425` |
| **tournament** | 3 | 297 | `tournament_member`, `tournament_kpi`, `tournament` |
| **wamm** | 3 | 177,104 | `wamm_message`, `wamm_chat`, `wamm_no_exist_number` |
| **address** | 2 | 1,524,032 | `address`, `address_audit` |
| **admUser** | 2 | 8,261 | `admUser_audit`, `admUser` |
| **advertisers** | 2 | 312,277 | `advertisers_click_statistic`, `advertisers` |
| **agent** | 2 | 3,159 | `agent_conversation_message`, `agent_conversation` |
| **api** | 2 | 1,919,230 | `api`, `api_leads` |
| **bank** | 2 | 385,964 | `bank_statements`, `bank_statement_uploads` |
| **cession** | 2 | 22,708 | `cession_loan`, `cession` |
| **communication** | 2 | 2,807,385 | `communication_history_item`, `communication_history` |
| **contact** | 2 | 1,480,114 | `contact_phone_audit`, `contact_phone` |
| **decision** | 2 | 533,555 | `decision`, `decision_module` |
| **dictionary** | 2 | 609 | `dictionary_translation`, `dictionary` |
| **email** | 2 | 2,607,744 | `email`, `email_sender` |
| **external** | 2 | 0 | `external_affiliate`, `external_wallet` |
| **income** | 2 | 1,009,265 | `income_audit`, `income` |
| **marketing** | 2 | 14,253 | `marketing_promo_participant`, `marketing_promo` |
| **outsourcing** | 2 | 0 | `outsourcing_contractor`, `outsourcing_unit` |
| **partner** | 2 | 4 | `partner_api_key`, `partner_api_request_log` |
| **pre** | 2 | 121 | `pre_legal_loan`, `pre_legal_campaign` |
| **product** | 2 | 9 | `product`, `product_matrix` |
| **return** | 2 | 102,276 | `return_discount_offer`, `return_discount_campaign` |
| **setting** | 2 | 406 | `setting_audit`, `setting` |
| **short** | 2 | 204,178 | `short_link`, `short_link_click` |
| **sms** | 2 | 17,427,090 | `sms`, `sms_sender` |
| **telegram** | 2 | 19 | `telegram_bot_private_chat`, `telegram_bot` |
| **tumi** | 2 | 23 | `tumi_pay_bank`, `tumi_pay_transfer_money` |
| **agreement** | 1 | 779,209 | `agreement` |
| **black** | 1 | 3,589 | `black_list` |
| **city** | 1 | 1,123 | `city` |
| **cross** | 1 | 25,418 | `cross_sell_banner_exposure` |
| **extension** | 1 | 59,664 | `extension` |
| **oz** | 1 | 738,276 | `oz_file_analysis` |
| **prolongation** | 1 | 78,969 | `prolongation_request` |
| **refresh** | 1 | 477,598 | `refresh_tokens` |
| **revisions** | 1 | 38,358,178 | `revisions` |
| **webitel** | 1 | 1,637,221 | `webitel_call` |

## Полный список таблиц (alphabetical)

<details><summary>раскрыть список из 255 таблиц</summary>

- `ab_allocation` — 35,148 строк, 6 колонок, 1 FK
- `ab_experiment` — 6 строк, 11 колонок
- `ab_experiment_event` — 0 строк, 6 колонок, 1 FK
- `action_tree` — 509 строк, 8 колонок, 2 FK
- `action_tree_catalog_group` — 47 строк, 9 колонок
- `action_tree_catalog_item` — 370 строк, 12 колонок, 1 FK
- `address` — 779,860 строк, 12 колонок, 4 FK
- `address_audit` — 744,172 строк, 14 колонок, 1 FK
- `admUser` — 245 строк, 29 колонок, 2 FK
- `admUser_audit` — 8,016 строк, 31 колонок, 1 FK
- `adm_user_absence` — 50 строк, 14 колонок, 4 FK
- `advertisers` — 3 строк, 8 колонок
- `advertisers_click_statistic` — 312,274 строк, 6 колонок, 2 FK
- `affiliate` — 26 строк, 12 колонок
- `affiliate_action` — 54 строк, 7 колонок, 1 FK
- `affiliate_event` — 521,361 строк, 9 колонок, 1 FK
- `affiliate_log` — 393,514 строк, 7 колонок, 1 FK
- `agent_conversation` — 1,123 строк, 12 колонок
- `agent_conversation_message` — 2,036 строк, 7 колонок, 1 FK
- `agreement` — 779,209 строк, 11 колонок, 2 FK
- `ai_prompt_template` — 14 строк, 17 колонок, 2 FK
- `ai_prompt_template_admin` — 26 строк, 2 колонок, 2 FK
- `ai_report` — 79 строк, 16 колонок, 3 FK
- `ai_report_schedule` — 6 строк, 19 колонок, 2 FK
- `ai_report_schedule_additional_recipient` — 10 строк, 2 колонок, 2 FK
- `ai_report_schedule_manager` — 12 строк, 2 колонок, 2 FK
- `ai_report_schedule_target_admin` — 1 строк, 2 колонок, 2 FK
- `api` — 1,883,793 строк, 11 колонок, 1 FK
- `api_leads` — 35,437 строк, 23 колонок, 2 FK
- `auto_debit_campaign` — 183 строк, 23 колонок, 5 FK
- `auto_debit_strategy` — 13 строк, 8 колонок, 2 FK
- `auto_debit_strategy_banks` — 34 строк, 2 колонок, 2 FK
- `auto_debit_strategy_step` — 31 строк, 4 колонок, 1 FK
- `aws_face_compare` — 174,015 строк, 6 колонок, 3 FK
- `aws_face_compare_match` — 175,713 строк, 4 колонок, 1 FK
- `aws_face_rekognition` — 801,838 строк, 4 колонок, 2 FK
- `aws_face_rekognition_match` — 482,603 строк, 4 колонок, 2 FK
- `aws_liveness_analysis` — 1,974 строк, 10 колонок, 2 FK
- `bank_statement_uploads` — 88 строк, 13 колонок, 1 FK
- `bank_statements` — 385,876 строк, 17 колонок, 3 FK
- `black_list` — 3,589 строк, 14 колонок
- `call_base_transfer_history` — 2,743,955 строк, 5 колонок, 2 FK
- `call_center_audience` — 421 строк, 8 колонок, 2 FK
- `call_center_call_base` — 349 строк, 21 колонок, 3 FK
- `call_center_campaign` — 227 строк, 13 колонок, 5 FK
- `call_center_campaign_cascade_step` — 0 строк, 7 колонок, 3 FK
- `call_center_campaign_cascade_step_run` — 0 строк, 8 колонок, 2 FK
- `call_center_campaign_run` — 5,202 строк, 14 колонок, 3 FK
- `card_operation` — 0 строк, 4 колонок, 1 FK
- `ceo_dashboard_plan` — 0 строк, 3 колонок
- `cession` — 8 строк, 37 колонок, 4 FK
- `cession_loan` — 22,700 строк, 3 колонок, 2 FK
- `city` — 1,123 строк, 7 колонок, 1 FK
- `cobre_collect_money` — 1,385,196 строк, 16 колонок, 5 FK
- `cobre_counterparty` — 143,694 строк, 6 колонок, 2 FK
- `cobre_direct_debit_registration` — 145,442 строк, 8 колонок, 1 FK
- `cobre_transfer_money` — 151,182 строк, 9 колонок, 1 FK
- `collection_agency_campaign` — 4 строк, 8 колонок, 3 FK
- `collection_agency_report` — 575 строк, 22 колонок, 3 FK
- `collection_call` — 1,356,488 строк, 19 колонок, 5 FK
- `collection_call_message` — 252,907 строк, 3 колонок, 1 FK
- `collection_category` — 5 строк, 5 колонок
- `collection_latam_strategy` — 76 строк, 7 колонок
- `collection_popup` — 9 строк, 12 колонок, 2 FK
- `collection_result_promise_to_pay` — 197,925 строк, 7 колонок, 3 FK
- `collector_assignment_history` — 499,743 строк, 8 колонок, 3 FK
- `collector_category_assignment` — 70 строк, 4 колонок, 2 FK
- `collector_notification` — 588,219 строк, 12 колонок, 2 FK
- `collector_notification_setting` — 6 строк, 5 колонок, 1 FK
- `collector_reassignment` — 10 строк, 9 колонок, 1 FK
- `collector_target` — 311 строк, 6 колонок, 1 FK
- `communication_history` — 450,783 строк, 17 колонок, 4 FK
- `communication_history_item` — 2,356,602 строк, 6 колонок, 3 FK
- `company_document` — 4 строк, 12 колонок, 1 FK
- `contact_phone` — 681,947 строк, 15 колонок, 5 FK
- `contact_phone_audit` — 798,167 строк, 17 колонок, 1 FK
- `contentElement` — 11 строк, 5 колонок
- `contentValue` — 8 строк, 4 колонок, 1 FK
- `cross_sell_banner_exposure` — 25,418 строк, 8 колонок, 1 FK
- `currency_exchange_rate` — 1 строк, 8 колонок, 2 FK
- `decision` — 272,836 строк, 7 колонок, 3 FK
- `decision_module` — 260,719 строк, 7 колонок, 1 FK
- `default_amount_fallback` — 0 строк, 3 колонок
- `default_amount_matrix_new` — 9 строк, 5 колонок
- `default_amount_matrix_repeated` — 198 строк, 6 колонок
- `dictionary` — 153 строк, 7 колонок
- `dictionary_translation` — 456 строк, 4 колонок, 1 FK
- `discount` — 255 строк, 8 колонок
- `discount_code` — 7,897 строк, 5 колонок, 3 FK
- `discount_condition` — 2 строк, 4 колонок, 1 FK
- `doctrine_migration_versions` — 149 строк, 3 колонок
- `druo_collect_money` — 1,940,208 строк, 17 колонок, 5 FK
- `druo_connect_account` — 98,995 строк, 9 колонок, 2 FK
- `druo_end_user` — 48,155 строк, 6 колонок, 1 FK
- `druo_transfer_money` — 15,171 строк, 12 колонок, 2 FK
- `duplicate_registration` — 127,078 строк, 4 колонок, 3 FK
- `duplicate_registration_attempt` — 341 строк, 5 колонок, 2 FK
- `duplicate_user_log` — 49,881 строк, 6 колонок
- `duplicate_user_photo_log` — 19,776 строк, 4 колонок, 1 FK
- `email` — 2,607,744 строк, 18 колонок, 3 FK
- `email_sender` — 0 строк, 3 колонок
- `extension` — 59,664 строк, 13 колонок, 3 FK
- `external_affiliate` — 0 строк, 8 колонок
- `external_wallet` — 0 строк, 4 колонок, 2 FK
- `file` — 1,338,378 строк, 13 колонок, 3 FK
- `file_matches` — 3,575 строк, 4 колонок, 2 FK
- `file_request` — 264,966 строк, 12 колонок, 5 FK
- `income` — 283,605 строк, 48 колонок, 5 FK
- `income_audit` — 725,660 строк, 50 колонок, 1 FK
- `journey_map_application` — 90,484 строк, 6 колонок, 2 FK
- `journey_map_event` — 1,992,664 строк, 7 колонок, 3 FK
- `journey_map_event_type` — 27 строк, 5 колонок
- `journey_map_loan` — 46,312 строк, 6 колонок, 2 FK
- `journey_map_user_tag` — 182,387 строк, 7 колонок, 1 FK
- `jurisdiction` — 29 строк, 5 колонок, 2 FK
- `loan` — 1,208,124 строк, 48 колонок, 10 FK
- `loan_additional_data` — 934,336 строк, 27 колонок, 2 FK
- `loan_audit` — 28,077,009 строк, 50 колонок, 1 FK
- `loan_auto_create_process` — 193 строк, 6 колонок, 1 FK
- `loan_auto_create_processed_loan` — 8,790 строк, 3 колонок, 2 FK
- `loan_auto_create_scheduler` — 2 строк, 8 колонок, 1 FK
- `loan_auto_decision_process` — 1,044,978 строк, 13 колонок, 3 FK
- `loan_auto_decision_workflow` — 1,043,828 строк, 4 колонок, 1 FK
- `loan_buyer` — 0 строк, 10 колонок
- `loan_calculation` — 96,616 строк, 5 колонок, 2 FK
- `loan_calculation_plan` — 10,669,318 строк, 7 колонок, 1 FK
- `loan_debt` — 202,402 строк, 5 колонок, 1 FK
- `loan_deny_reason` — 49 строк, 12 колонок, 2 FK
- `loan_extra_product` — 0 строк, 4 колонок, 2 FK
- `loan_giveout_attempt` — 196,675 строк, 2 колонок, 1 FK
- `loan_note` — 1,625,681 строк, 8 колонок, 2 FK
- `loan_note_audit` — 1,841,673 строк, 10 колонок, 1 FK
- `loan_processing_result` — 0 строк, 8 колонок, 3 FK
- `loan_rating` — 0 строк, 5 колонок, 1 FK
- `loan_request` — 979,523 строк, 26 колонок, 1 FK
- `loan_returned_params` — 0 строк, 5 колонок, 3 FK
- `loan_sold_information` — 0 строк, 5 колонок, 2 FK
- `loan_transaction` — 11,871,339 строк, 8 колонок, 2 FK
- `loan_transition_history` — 4,298,681 строк, 11 колонок, 4 FK
- `loyalty_level` — 0 строк, 9 колонок
- `marketing_promo` — 3 строк, 10 колонок, 2 FK
- `marketing_promo_participant` — 14,250 строк, 10 колонок, 3 FK
- `ms_teams_conversation_link` — 2 строк, 7 колонок, 1 FK
- `ms_teams_outgoing_jira_link` — 184 строк, 5 колонок
- `ms_teams_processed_activity` — 10 строк, 2 колонок
- `outsourcing_contractor` — 0 строк, 2 колонок
- `outsourcing_unit` — 0 строк, 5 колонок, 2 FK
- `oz_file_analysis` — 738,276 строк, 11 колонок, 2 FK
- `partner_api_key` — 4 строк, 8 колонок, 2 FK
- `partner_api_request_log` — 0 строк, 5 колонок, 1 FK
- `payment_details` — 104,879,964 строк, 4 колонок, 1 FK
- `payment_operation` — 113,196,240 строк, 8 колонок, 1 FK
- `payment_provider` — 11 строк, 5 колонок
- `payment_provider_balance` — 277 строк, 6 колонок
- `payment_registry` — 218,833 строк, 10 колонок, 3 FK
- `payment_reminder` — 0 строк, 4 колонок
- `payment_transaction` — 3,761,872 строк, 26 колонок, 5 FK
- `peerberry_process` — 11 строк, 10 колонок, 1 FK
- `peerberry_process_result` — 102,788 строк, 8 колонок, 2 FK
- `peerberry_setting` — 1 строк, 8 колонок
- `postman_block_rule` — 0 строк, 10 колонок, 1 FK
- `postman_department` — 7 строк, 6 колонок, 1 FK
- `postman_department_adm_user` — 0 строк, 2 колонок, 2 FK
- `postman_department_email` — 10 строк, 5 колонок, 1 FK
- `postman_email` — 21,319 строк, 36 колонок, 10 FK
- `postman_email_attachment` — 3,628 строк, 8 колонок, 1 FK
- `postman_email_category` — 39 строк, 8 колонок, 1 FK
- `postman_email_result` — 4 строк, 5 колонок, 1 FK
- `postman_legal_petition_radicado` — 327 строк, 2 колонок, 1 FK
- `postman_quick_answer` — 17 строк, 10 колонок, 1 FK
- `pre_legal_campaign` — 1 строк, 33 колонок, 3 FK
- `pre_legal_loan` — 120 строк, 8 колонок, 2 FK
- `price_element` — 9 строк, 7 колонок, 1 FK
- `price_matrix` — 0 строк, 10 колонок, 2 FK
- `price_setting` — 9 строк, 12 колонок, 1 FK
- `process` — 14 строк, 8 колонок
- `product` — 9 строк, 5 колонок
- `product_matrix` — 0 строк, 10 колонок, 3 FK
- `prolongation_request` — 78,969 строк, 16 колонок, 5 FK
- `pse_bank` — 44 строк, 6 колонок
- `refresh_tokens` — 477,598 строк, 4 колонок
- `region` — 33 строк, 7 колонок
- `report` — 2 строк, 6 колонок, 1 FK
- `report_result` — 3 строк, 6 колонок, 1 FK
- `report_task` — 3,154 строк, 14 колонок, 1 FK
- `report_task_file` — 2,755 строк, 8 колонок, 1 FK
- `return_discount_campaign` — 394 строк, 21 колонок, 5 FK
- `return_discount_offer` — 101,882 строк, 10 колонок, 3 FK
- `revisions` — 38,358,178 строк, 3 колонок
- `salary_request` — 93 строк, 8 колонок, 3 FK
- `sensitive_setting` — 0 строк, 4 колонок
- `setting` — 41 строк, 14 колонок
- `setting_audit` — 365 строк, 16 колонок, 1 FK
- `short_link` — 167,246 строк, 6 колонок, 1 FK
- `short_link_click` — 36,932 строк, 3 колонок, 1 FK
- `siigo_customer` — 2,549 строк, 6 колонок, 1 FK
- `siigo_fetched_invoice` — 0 строк, 10 колонок
- `siigo_fetched_invoice_item` — 0 строк, 11 колонок, 1 FK
- `siigo_invoice` — 67 строк, 16 колонок, 2 FK
- `siigo_invoice_item` — 233 строк, 8 колонок, 1 FK
- `sls_application` — 126,196 строк, 4 колонок, 1 FK
- `sls_application_attempt` — 92,181 строк, 11 колонок, 1 FK
- `sls_application_enrich_data` — 14,407 строк, 8 колонок, 1 FK
- `sls_application_response` — 174,026 строк, 5 колонок, 1 FK
- `sms` — 17,427,089 строк, 13 колонок, 3 FK
- `sms_sender` — 1 строк, 2 колонок
- `system_event_notification` — 25 строк, 9 колонок, 4 FK
- `telegram_bot` — 0 строк, 2 колонок
- `telegram_bot_private_chat` — 19 строк, 5 колонок, 2 FK
- `template_email` — 92 строк, 6 колонок
- `template_sms` — 338 строк, 8 колонок
- `template_web` — 0 строк, 3 колонок
- `threshold_alert_log` — 0 строк, 5 колонок, 1 FK
- `threshold_alert_rule` — 7 строк, 14 колонок
- `threshold_alert_rule_recipient` — 9 строк, 2 колонок, 2 FK
- `threshold_inactive_staff_alert` — 82 строк, 9 колонок, 4 FK
- `tmp_ai_report_schedule_backup_20260425` — 6 строк, 18 колонок
- `tmp_ai_report_schedule_manager_backup_20260425` — 14 строк, 2 колонок
- `tmp_ai_report_schedule_target_admin_backup_20260425` — 7 строк, 2 колонок
- `tournament` — 6 строк, 11 колонок
- `tournament_kpi` — 12 строк, 4 колонок, 1 FK
- `tournament_member` — 279 строк, 14 колонок, 3 FK
- `tumi_pay_bank` — 23 строк, 5 колонок, 1 FK
- `tumi_pay_transfer_money` — 0 строк, 10 колонок, 1 FK
- `user` — 976,448 строк, 41 колонок, 3 FK
- `user_account` — 1,008,857 строк, 4 колонок, 1 FK
- `user_account_audit` — 1,344,612 строк, 6 колонок, 1 FK
- `user_additional_data` — 1,106,156 строк, 21 колонок, 1 FK
- `user_audit` — 8,203,924 строк, 43 колонок, 1 FK
- `user_bank` — 586,715 строк, 11 колонок, 3 FK
- `user_bank_audit` — 775,597 строк, 13 колонок, 1 FK
- `user_device_info` — 2,579,594 строк, 22 колонок, 3 FK
- `user_duplicate_registration_attempt` — 213 строк, 2 колонок, 2 FK
- `user_employment` — 750,487 строк, 15 колонок, 5 FK
- `user_event` — 27,399,103 строк, 9 колонок, 2 FK
- `user_event_notification` — 51 строк, 16 колонок
- `user_event_notification_condition` — 1 строк, 5 колонок, 1 FK
- `user_loyalty_program` — 55,618 строк, 4 колонок, 1 FK
- `user_note` — 2,407,022 строк, 8 колонок, 2 FK
- `user_note_audit` — 2,997,350 строк, 10 колонок, 1 FK
- `user_notification_campaign` — 16 строк, 15 колонок, 1 FK
- `user_otp` — 1,014,417 строк, 6 колонок, 1 FK
- `user_processing_result` — 95,101 строк, 6 колонок, 2 FK
- `user_registration` — 1,018,354 строк, 7 колонок, 1 FK
- `user_subscription` — 1,014,683 строк, 6 колонок, 1 FK
- `user_transition_history` — 1,061,023 строк, 9 колонок, 2 FK
- `user_virtual_account` — 0 строк, 7 колонок, 2 FK
- `user_visits` — 2,939,498 строк, 5 колонок, 1 FK
- `verifier_auto_assignment` — 1 строк, 2 колонок
- `vivat_pay_transfer_money` — 0 строк, 11 колонок, 1 FK
- `wamm_chat` — 7,144 строк, 6 колонок
- `wamm_message` — 169,958 строк, 18 колонок, 2 FK
- `wamm_no_exist_number` — 2 строк, 4 колонок, 1 FK
- `webitel_call` — 1,637,221 строк, 27 колонок, 1 FK
- `whatsapp_chat_before_sign` — 623 строк, 6 колонок, 2 FK
</details>

## Подробно — ключевые таблицы

Колонки даны в порядке `ordinal_position`. Маркеры: **PK** — primary, **UNI** — unique, **IDX** — индекс. Комментарии Doctrine из `column_comment` сохранены.

### `user` — 976,448 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `education_id` | `int` | IDX |  |
| `current_processing_result_id` | `int` | **UNI** |  |
| `admin_version` | `int` |  |  |
| `first_name` | `varchar(255)` | IDX |  |
| `last_name` | `varchar(255)` |  |  |
| `email` | `varchar(255)` |  |  |
| `email_verification_status` | `int` |  | (DC2Type:email_verification_status_type) |
| `status` | `int` | IDX | (DC2Type:user_status) |
| `main_phone_number` | `varchar(255)` | IDX |  |
| `is_confirmed` | `tinyint(1)` |  |  |
| `sms_confirmation_code` | `varchar(10)` |  |  |
| `gender` | `smallint` |  | (DC2Type:gender_type) |
| `birth_date` | `date` | IDX |  |
| `number_of_children` | `int` |  |  |
| `persId` | `varchar(100)` | IDX |  |
| `place_of_id_issue` | `varchar(255)` |  |  |
| `pers_id_issue_date` | `date` |  |  |
| `previous_id_number` | `varchar(255)` | IDX |  |
| `registrationDate` | `datetime` | IDX |  |
| `registration_ip` | `varchar(60)` | IDX |  |
| `lang` | `varchar(5)` |  |  |
| `block_type` | `int` |  | (DC2Type:user_block_type) |
| `target_url` | `text` |  |  |
| `method_of_disbursement` | `int` |  |  |
| `requested_amount` | `int` |  |  |
| `requested_days` | `int` |  |  |
| `lastActivity` | `datetime` |  |  |
| `denyTillDate` | `datetime` |  |  |
| `block_since_date` | `datetime` |  |  |
| `unblock_since_date` | `datetime` |  |  |
| `loans_before` | `varchar(1000)` |  |  |
| `password` | `varchar(64)` |  |  |
| `salt` | `varchar(20)` |  |  |
| `assigned_admin_at` | `datetime` |  |  |
| `registration_steps` | `int` | IDX |  |
| `marked_as_deleted` | `tinyint(1)` |  |  |
| `returned_loans_count` | `int` |  |  |
| `aggregate_updated_at` | `datetime` |  |  |
| `assignedAdminId` | `int` | IDX |  |
| `confirmed_by_type` | `int` |  | (DC2Type:confirmed_by_type) |

**Foreign keys:**
- `assignedAdminId` → `admUser.id`
- `current_processing_result_id` → `user_processing_result.id`
- `education_id` → `dictionary.id`

### `loan` — 1,208,124 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `collector_id` | `int` | IDX |  |
| `product_id` | `int` | IDX |  |
| `price_id` | `int` | IDX |  |
| `deny_reason_id` | `int` | IDX |  |
| `hotline_admin_id` | `int` | IDX |  |
| `call_manager_id` | `int` | IDX |  |
| `creator_manager_id` | `int` | IDX |  |
| `admin_version` | `int` |  |  |
| `publicId` | `varchar(100)` |  |  |
| `request_amount` | `decimal(10,2)` | IDX |  |
| `request_commission` | `decimal(10,2)` |  |  |
| `requestDate` | `datetime` | IDX |  |
| `approveDate` | `datetime` |  |  |
| `giveDate` | `datetime` |  |  |
| `mustPayDate` | `date` | IDX |  |
| `mustPayDateOrig` | `date` |  |  |
| `daysLate` | `smallint` |  |  |
| `statusChangeDate` | `datetime` |  |  |
| `returnedDate` | `datetime` |  |  |
| `term` | `smallint` | IDX |  |
| `status` | `int` | IDX | (DC2Type:loan_status_type) |
| `subStatus` | `int` | IDX |  |
| `lastExtensionDate` | `datetime` |  |  |
| `activationCode` | `varchar(8)` |  |  |
| `currency` | `varchar(8)` |  |  |
| `requestCurrency` | `varchar(5)` |  |  |
| `smsConfirmed` | `tinyint(1)` |  |  |
| `admin_assignment_date` | `datetime` |  |  |
| `loyalty_discount_percent` | `smallint` |  |  |
| `smsConfirmedDate` | `datetime` |  |  |
| `daysLateMax` | `smallint` |  |  |
| `give_out_provider` | `varchar(255)` |  |  |
| `target_url` | `text` |  |  |
| `collection_order` | `int` |  |  |
| `need_review_at` | `datetime` |  |  |
| `collection_work_at` | `datetime` |  |  |
| `cession_allowed` | `tinyint(1)` |  |  |
| `adm_verification_requested_at` | `datetime` |  |  |
| `adm_verification_sent_at` | `datetime` |  |  |
| `method_of_disbursement` | `smallint` | IDX |  |
| `signature_code` | `varchar(255)` |  |  |
| `counteroffer_expired_at` | `datetime` |  |  |
| `calculated_at` | `datetime` |  |  |
| `userId` | `int` | IDX |  |
| `assignedAdminId` | `int` | IDX |  |
| `approveAdminId` | `int` | IDX |  |
| `counteroffer_approved_amount` | `decimal(12,2)` |  |  |

**Foreign keys:**
- `approveAdminId` → `admUser.id`
- `assignedAdminId` → `admUser.id`
- `call_manager_id` → `admUser.id`
- `collector_id` → `admUser.id`
- `creator_manager_id` → `admUser.id`
- `deny_reason_id` → `loan_deny_reason.id`
- `hotline_admin_id` → `admUser.id`
- `price_id` → `price_element.id`
- `product_id` → `product.id`
- `userId` → `user.id`

### `sms` — 17,427,089 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `phone` | `varchar(15)` |  |  |
| `message` | `text` |  |  |
| `response` | `varchar(200)` |  |  |
| `sendDate` | `datetime` |  |  |
| `status` | `varchar(20)` |  |  |
| `sender` | `varchar(15)` |  |  |
| `responseId` | `varchar(70)` | IDX |  |
| `smsProvider` | `varchar(50)` |  |  |
| `template` | `varchar(250)` |  |  |
| `userId` | `int` | IDX |  |
| `campaign_run_id` | `int` | IDX |  |
| `cascade_step_run_id` | `int` | IDX |  |

**Foreign keys:**
- `campaign_run_id` → `call_center_campaign_run.id`
- `cascade_step_run_id` → `call_center_campaign_cascade_step_run.id`
- `userId` → `user.id`

### `email` — 2,607,744 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `createdAt` | `datetime` |  |  |
| `nameTo` | `varchar(255)` |  |  |
| `emailTo` | `varchar(255)` |  |  |
| `sendDate` | `datetime` |  |  |
| `topic` | `varchar(255)` |  |  |
| `templateId` | `int` |  |  |
| `data` | `text` |  |  |
| `content` | `mediumtext` |  |  |
| `sendMethod` | `varchar(20)` |  |  |
| `nameFrom` | `varchar(255)` |  |  |
| `emailFrom` | `varchar(50)` |  |  |
| `status` | `varchar(255)` |  |  |
| `response` | `mediumtext` |  |  |
| `userId` | `int` | IDX |  |
| `readAt` | `datetime` |  |  |
| `campaign_run_id` | `int` | IDX |  |
| `cascade_step_run_id` | `int` | IDX |  |

**Foreign keys:**
- `campaign_run_id` → `call_center_campaign_run.id`
- `cascade_step_run_id` → `call_center_campaign_cascade_step_run.id`
- `userId` → `user.id`

### `address` — 779,860 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `user_id` | `int` | IDX |  |
| `region_id` | `int` | IDX |  |
| `city_id` | `int` | IDX |  |
| `street_type_id` | `int` | IDX |  |
| `type` | `int` |  | (DC2Type:contact_address_type) |
| `neighborhood` | `varchar(255)` |  |  |
| `house` | `varchar(255)` | IDX |  |
| `created_at` | `datetime` |  |  |
| `updated_at` | `datetime` |  |  |
| `created_by` | `varchar(255)` |  |  |
| `updated_by` | `varchar(255)` |  |  |

**Foreign keys:**
- `city_id` → `city.id`
- `region_id` → `region.id`
- `street_type_id` → `dictionary.id`
- `user_id` → `user.id`

### `income` — 283,605 строк

| Колонка | Тип | Ключ | Комментарий |
|---|---|---|---|
| `id` | `int` | **PK** |  |
| `collector_id` | `int` | IDX |  |
| `creator_id` | `int` | IDX |  |
| `discount_offer_id` | `int` | IDX |  |
| `sub_status` | `int` | IDX |  |
| `income_date` | `datetime` | IDX |  |
| `created_at` | `datetime` |  |  |
| `bank_payment_id` | `varchar(250)` | IDX |  |
| `income` | `decimal(10,2)` |  |  |
| `body` | `decimal(10,2)` |  |  |
| `body_clean` | `decimal(10,2)` |  |  |
| `body_vat` | `decimal(10,2)` |  |  |
| `write_off_for_body` | `decimal(10,2)` |  |  |
| `commission` | `decimal(10,2)` |  |  |
| `commission_clean` | `decimal(10,2)` |  |  |
| `commission_vat` | `decimal(10,2)` |  |  |
| `write_off_for_commission` | `decimal(10,2)` |  |  |
| `extra_commission` | `decimal(10,2)` |  |  |
| `extra_commission_clean` | `decimal(10,2)` |  |  |
| `extra_commission_vat` | `decimal(10,2)` |  |  |
| `write_off_for_extra_commission` | `decimal(10,2)` |  |  |
| `paid_sms_notification_price` | `decimal(10,2)` |  |  |
| `write_off_for_sms_notification_price` | `decimal(10,2)` |  |  |
| `paid_virtual_acc_creating_price` | `decimal(10,2)` |  |  |
| `write_off_for_virtual_acc_creating_price` | `decimal(10,2)` |  |  |
| `fine` | `decimal(10,2)` |  |  |
| `fine_clean` | `decimal(10,2)` |  |  |
| `fine_vat` | `decimal(10,2)` |  |  |
| `write_off_for_fine` | `decimal(10,2)` |  |  |
| `deposit` | `decimal(10,2)` |  |  |
| `give_out_commission` | `decimal(10,2)` |  |  |
| `give_out_commission_clean` | `decimal(10,2)` |  |  |
| `give_out_commission_vat` | `decimal(10,2)` |  |  |
| `write_off_for_give_out_commission` | `decimal(10,2)` |  |  |
| `is_manually_allocated` | `tinyint(1)` |  |  |
| `is_extend` | `tinyint(1)` |  |  |
| `is_returned` | `tinyint(1)` |  |  |
| `is_sold` | `tinyint(1)` |  |  |
| `is_force_close` | `tinyint(1)` |  |  |
| `loan_id` | `int` | IDX |  |
| `payment_provider_id` | `int` | IDX |  |
| `manual_external_id` | `varchar(250)` | IDX |  |
| `is_after_sold` | `tinyint(1)` |  |  |
| `is_from_deposit` | `tinyint(1)` |  |  |
| `is_refund` | `tinyint(1)` |  |  |
| `refund_attempt_at` | `datetime` |  |  |
| `deposit_refunded_at` | `datetime` |  |  |
| `payment_provider_subtype` | `varchar(20)` |  |  |

**Foreign keys:**
- `collector_id` → `admUser.id`
- `creator_id` → `admUser.id`
- `discount_offer_id` → `return_discount_offer.id`
- `loan_id` → `loan.id`
- `payment_provider_id` → `payment_provider.id`

## Подсказки для навигации

- **Поиск клиента по телефону:** `user.main_phone_number` (varchar 255, индексирован). Связанные телефоны — в `user_phone`.
- **Активные займы клиента:** `loan` JOIN `user` ON `loan.userId = user.id`. Статус — `loan.status` (`DC2Type:loan_status_type`), даты — `requestDate`/`giveDate`/`mustPayDate`/`returnedDate`, дни просрочки — `daysLate`.
- **Платежи:** `payment` (содержит ~222M строк — самая большая таблица). Связь с `loan` обычно по `payment.loan_id` или через `payment_log`.
- **История коммуникаций:** `communication_log` (~2.8M). По SMS — `sms`/`sms_log` (~17M+), почтовые — `email`/`email_log` (~2.6M+).
- **Звонки:** prefix `call_*` (7 таблиц, ~2.75M строк) — история обзвонов и запись.
- **Коллекторская работа:** prefix `collection_*` и `collector_*` — назначения, события, отчёты.
- **Wamm / Druo / Cobre / SLS** — внешние процессинги/платёжные провайдеры.
- **Postman** (10 таблиц) — внутренние очереди рассылок.
- **AI** (7 таблиц) — экспериментальные AI-фичи (мало данных).
- **Журналы / журнеи** — `journey_*` (~2.3M) хранят клиентский путь.