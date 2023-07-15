# Copyright 2023 Kitti U.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import requests
import json
from odoo import _, api, models
from odoo.exceptions import ValidationError


class PushToFrappe(models.AbstractModel):
    _name = "push.to.frappe"

    @api.model
    def push(self, target_doctype, target_docs, push_comment=True, push_file=False):
        # Connection to Frappe``
        auth_token = self.env["ir.config_parameter"].sudo().get_param("frappe.auth.token")
        server_url = self.env["ir.config_parameter"].sudo().get_param("frappe.server.url")
        if not auth_token or not server_url:
            raise ValidationError(
                _("Cannot connect to Frappe Server.\n"
                  "System parameters frappe.server.url, frappe.auth.token not found")
            )
        headers = {"Authorization": "token %s" % auth_token}
        frappe_docs = self._create_frappe_docs(
            headers, server_url, target_doctype, target_docs, push_comment, push_file
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': True,
                'title': _("Data pushed to %s") % server_url,
                'message': "<br>".join([
                    "%s ⇌ <a href='%s/app/%s/%s' target='_blank' rel='noopener noreferrer'>%s</a>" %
                    (x[0], server_url, target_doctype.replace(" ", "-").lower(), x[1], x[1])
                    for x in frappe_docs
                ]),
            }
        }

    @api.model
    def _create_frappe_docs(self, headers, server_url, target_doctype, target_docs, push_comment, push_file):
        frappe_docs = []
        for doc in target_docs:
            (odoo_model, odoo_id, odoo_ref) = (False, False, False)
            if doc.get("odoo_ref"):
                (odoo_model, odoo_id, odoo_ref) = doc["odoo_ref"].split(",")
                doc.update({"odoo_ref": odoo_ref, "custom_odoo_ref": odoo_ref})
            else:
                raise ValidationError(_("Odoo Ref required, please check data map in server action"))
            # Create frappe document
            res_json = requests.post(
                url="%s/api/resource/%s" % (server_url, target_doctype),
                json={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                headers=headers,
                data=json.dumps(doc)
            ).json()
            if not res_json.get("data"):
                raise ValidationError(res_json.get("_server_messages", res_json.get("exception")))
            frappe_doc = res_json['data']['name']
            frappe_docs.append((odoo_ref or "-", frappe_doc))
            # Push files
            if push_file:
                self._push_file(headers, server_url, odoo_model, odoo_id, target_doctype, frappe_doc)
            # Push comments
            if push_comment:
                self._push_comment(headers, server_url, odoo_model, odoo_id, target_doctype, frappe_doc)
        return frappe_docs

    @api.model
    def _push_comment(self, headers, server_url, odoo_model, odoo_id, target_doctype, frappe_doc):
        odoo_doc = self.env[odoo_model].browse(int(odoo_id))
        if 'message_ids' in odoo_doc and odoo_doc.message_ids:
            messages = odoo_doc.message_ids.sorted("date").filtered("body")
            for message in messages:
                comment = {
                    "comment_type": "Comment",
                    "reference_doctype": target_doctype,
                    "reference_name": frappe_doc,
                    "content": "%s<b>By: </b>%s <b>Dated: </b> %s" % (
                        message.body,
                        message.author_id.name,
                        message.date.strftime("%d/%m/%Y"),
                    )
                }
                requests.post(
                    url="%s/api/resource/%s" % (server_url, "Comment"),
                    json={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    headers=headers,
                    data=json.dumps(comment)
                )

    @api.model
    def _push_file(self, headers, server_url, odoo_model, odoo_id, target_doctype, frappe_doc):
        files = self.env["ir.attachment"].search([("res_model", "=", odoo_model), ("res_id", "=", odoo_id)])
        for file in files:
            data = {
                "filename": file.name,
                "filedata": file.datas,
                "doctype": target_doctype,
                "docname": frappe_doc,
                "is_private": 1,
                "decode_base64": 1
            }
            requests.post(
                url="%s/api/method/frappe.client.attach_file" % server_url,
                json={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                headers=headers,
                data=data
            )
