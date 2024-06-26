from datetime import datetime

from flask import Blueprint, url_for, redirect, request

from app import db
from app.models import Question, Answer

bp = Blueprint('answer', __name__, url_prefix='/answer')


@bp.route('/create/<int:question_id>', methods=('POST',))
def create(question_id):
  question = Question.query.get_or_404(question_id)
  content = request.form['content']
  answer = Answer(question=question, content=content, create_date=datetime.now())
  db.session.add(answer)
  db.session.commit()
  return redirect(url_for('question.detail', question_id=question_id))