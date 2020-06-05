from CTFd.plugins import register_plugin_assets_directory, register_user_page_menu_bar
from CTFd.plugins.challenges import BaseChallenge, CHALLENGE_CLASSES
from CTFd.plugins.flags import get_flag_class
from CTFd.models import (
    db,
    Solves,
    Fails,
    Flags,
    Challenges,
    ChallengeFiles,
    Tags,
    Hints,
)
from CTFd.utils.user import get_ip, get_current_user
from CTFd.utils.uploads import delete_file
from CTFd.utils.modes import get_model
from CTFd.utils.logging import log
from CTFd.utils.decorators import (
    require_verified_emails,
    authed_only
)
from flask import Blueprint, render_template
from sqlalchemy.sql import and_


class SteamChallenge(BaseChallenge):
    id = "steam"  # Unique identifier used to register challenges
    name = "steam"  # Name of a challenge type
    templates = {  # Templates used for each aspect of challenge editing & viewing
        "create": "/plugins/steam_challenge/assets/create.html",
        "update": "/plugins/steam_challenge/assets/update.html",
        "view": "/plugins/steam_challenge/assets/view.html",
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        "create": "/plugins/steam_challenge/assets/create.js",
        "update": "/plugins/steam_challenge/assets/update.js",
        "view": "/plugins/steam_challenge/assets/view.js",
    }
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = "/plugins/steam_challenge/assets/"
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint(
        "steam_challenge",
        __name__,
        template_folder="templates",
        static_folder="assets"
    )

    @staticmethod
    def create(request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        data = request.form or request.get_json()
        challenge = SteamChallengeModel(**data)

        db.session.add(challenge)
        db.session.commit()

        return challenge

    @staticmethod
    def read(challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        challenge = SteamChallengeModel.query.filter_by(id=challenge.id).first()
        data = {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "description": challenge.description,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            "type_data": {
                "id": SteamChallenge.id,
                "name": SteamChallenge.name,
                "templates": SteamChallenge.templates,
                "scripts": SteamChallenge.scripts,
            },
        }
        return data

    @staticmethod
    def update(challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()
        for attr, value in data.items():
            setattr(challenge, attr, value)

        db.session.commit()
        return challenge

    @staticmethod
    def delete(challenge):
        """
        This method is used to delete the resources used by a challenge.

        :param challenge:
        :return:
        """
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        SteamChallengeModel.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    @staticmethod
    def attempt(challenge, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param challenge: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        chal = SteamChallengeModel.query.filter_by(id=challenge.id).first()
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        for flag in flags:
            if get_flag_class(flag.type).compare(flag, submission):
                Model = get_model()
                solve_count = (
                    Solves.query.join(Model, Solves.account_id == Model.id)
                    .filter(
                        Solves.challenge_id == challenge.id,
                        Model.hidden == False,
                        Model.banned == False,
                    )
                    .count()
                )
                if solve_count == 0:
                    return True, "Congratulations - you were first to solve this, check the Steam Keys page for your key!"
                return True, "Correct"
        return False, "Incorrect"

    @staticmethod
    def solve(user, team, challenge, request):
        """
        This method is used to insert Solves into the database in order to mark a challenge as solved.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        chal = SteamChallengeModel.query.filter_by(id=challenge.id).first()
        data = request.form or request.get_json()
        submission = data["submission"].strip()

        # If we're the first solver - record that
        Model = get_model()
        solve_count = (
            Solves.query.join(Model, Solves.account_id == Model.id)
            .filter(
                Solves.challenge_id == challenge.id,
                Model.hidden == False,
                Model.banned == False,
            )
            .count()
        )
        if solve_count == 0:
            chal.first_solver = user.account_id
            db.session.add(chal)

        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission,
        )
        db.session.add(solve)
        db.session.commit()
        db.session.close()

    @staticmethod
    def fail(user, team, challenge, request):
        """
        This method is used to insert Fails into the database in order to mark an answer incorrect.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        wrong = Fails(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(request),
            provided=submission,
        )
        db.session.add(wrong)
        db.session.commit()
        db.session.close()


def get_chal_class(class_id):
    """
    Utility function used to get the corresponding class from a class ID.

    :param class_id: String representing the class ID
    :return: Challenge class
    """
    cls = CHALLENGE_CLASSES.get(class_id)
    if cls is None:
        raise KeyError
    return cls

class SteamChallengeModel(Challenges):
    __mapper_args__ = {"polymorphic_identity": "steam"}
    id = db.Column(None, db.ForeignKey("challenges.id"), primary_key=True)
    steam_key = db.Column(db.Text, default="")
    steam_gamename = db.Column(db.Text, default="")
    # I probably don't need todo this but don't really want to write the SQL query to get the first solver
    first_solver = db.Column(db.Integer, db.ForeignKey("users.id"))
    def __init__(self, *args, **kwargs):
        super(SteamChallengeModel, self).__init__(**kwargs)

def load(app):
    # upgrade()
    app.db.create_all()
    CHALLENGE_CLASSES["steam"] = SteamChallenge
    register_plugin_assets_directory(
        app, base_path="/plugins/steam_challenge/assets/"
    )

    register_user_page_menu_bar("Steam Keys", "steamkeys")
    blueprint = Blueprint(
        "steam_challenge",
        __name__,
        template_folder="templates",
        static_folder="assets"
    )
    @blueprint.route("/steamkeys", methods=["GET", "POST"])
    @require_verified_emails
    @authed_only
    def view_keys():
        user = get_current_user()
        chals = SteamChallengeModel.query.filter_by(first_solver=user.account_id).order_by(SteamChallengeModel.id.asc()).all()
        my_keys = []
        for chal in chals:
            d = SteamChallenge.read(chal)
            d["steam_key"] = chal.steam_key
            d["steam_gamename"] = chal.steam_gamename
            my_keys.append(d)

        return render_template("steamkeys.html", keys=my_keys)
    app.register_blueprint(blueprint)
