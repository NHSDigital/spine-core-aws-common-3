"""
Module for MESH API functionality for step functions
"""
import os
from http import HTTPStatus

from mesh_aws_client.mesh_common import MeshCommon, SingletonCheckFailure
from mesh_aws_client.mesh_mailbox import MeshMailbox
from spine_aws_common import LambdaApplication


class MeshPollMailboxApplication(LambdaApplication):
    """
    MESH API Lambda for sending a message
    """

    def __init__(self, additional_log_config=None, load_ssm_params=False):
        """
        Init variables
        """
        super().__init__(additional_log_config, load_ssm_params)
        self.mailbox_name = None
        self.environment = os.environ.get("Environment", "default")
        self.get_messages_step_function_name = self.system_config.get(
            "GET_MESSAGES_STEP_FUNCTION_NAME", f"{self.environment}-get-messages"
        )
        self.handshake = "false"

    def initialise(self):
        # initialise
        self.mailbox_name = self.event["mailbox"]
        self.handshake = self.event.get("handshake", "false")

    def start(self):
        # in case of crash
        self.response = {"statusCode": HTTPStatus.INTERNAL_SERVER_ERROR.value}

        mailbox = MeshMailbox(self.log_object, self.mailbox_name, self.environment)
        if self.handshake.lower() == "true":
            mailbox.handshake()
            # 204 No Content is raised so the step function
            # ends without looking for messages
            self.response = {"statusCode": HTTPStatus.NO_CONTENT.value, "body": {}}
            return

        try:
            MeshCommon.singleton_check(
                self.mailbox_name,
                self.get_messages_step_function_name,
            )
        except SingletonCheckFailure as e:
            self.response = MeshCommon.return_failure(
                self.log_object,
                HTTPStatus.TOO_MANY_REQUESTS.value,
                "MESHPOLL0002",
                self.mailbox_name,
                message=e.msg,
            )
            return
        list_response, message_list = mailbox.list_messages()
        list_response.raise_for_status()
        message_count = len(message_list)
        output_list = []
        if message_count == 0:
            # return 204 to keep state transitions to minimum if no messages
            self.response = {"statusCode": HTTPStatus.NO_CONTENT.value, "body": {}}
            return
        for message in message_list:
            output_list.append(
                {
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "complete": False,
                        "internal_id": self.log_object.internal_id,
                        "message_id": message,
                        "dest_mailbox": self.mailbox_name,
                    },
                }
            )

        self.log_object.write_log(
            "MESHPOLL0001",
            None,
            {
                "mailbox": self.mailbox_name,
                "message_count": message_count,
            },
        )

        # to set response for the lambda
        self.response = {
            "statusCode": HTTPStatus.OK.value,
            "headers": {"Content-Type": "application/json"},
            "body": {
                "internal_id": self.log_object.internal_id,
                "message_count": message_count,
                "message_list": output_list,
            },
        }

        mailbox.clean_up()


# create instance of class in global space
# this ensures initial setup of logging/config is only done on cold start
app = MeshPollMailboxApplication()


def lambda_handler(event, context):
    """Standard lambda_handler"""
    return app.main(event, context)
