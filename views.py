# -*- coding: utf-8 -*-
# import the Flask class from the flask module
import urllib
from functools import wraps

from flask import flash, redirect, render_template, \
    request, url_for, session
from flask.blueprints import Blueprint
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from _config import basedir, BITLY_USER, BITLY_KEY
from app.models import User, Feed, SharedItem
from bitlyapi import bitlyapi
from db import db
from feeds import parse_feeds, set_title_by_feed, relevant_feeds,relevant_feeds_urls, get_project_by_feed_url
from forms import RegisterForm, LoginForm, AddFeedForm

notifier = Blueprint('notifier', __name__,
                     template_folder='templates',
                     static_folder='static',
                     )

def login_required(test):
    @wraps(test)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return test(*args, **kwargs)
        else:
            flash(u'עליך להירשם ולהתחבר לאתר.')
            return redirect(url_for('notifier.login'))

    return wrap


@notifier.route('/', methods=['GET', 'POST'])
def login():
    print(url_for('static',filename='notifier.png'))
    error = None
    form = LoginForm(request.form)
    if request.method == "POST":
        if form.validate_on_submit():
            user = User.query.filter_by(email=request.form['email']).first()
            if user is not None and user.password == request.form['password']:
                session['logged_in'] = True
                session['user_id'] = user.id
                session['user_email'] = user.email
                flash(u'ברוכים הבאים, תהנו!')
                return redirect(url_for('notifier.feeds_editor'))
            else:
                error = 'כתובת דוא"ל או סיסמה שגויים'
        else:
            error = "שני השדות דרושים להתחברות."
    return render_template("login.html", form=form, error=error)


@notifier.route('/logout/')
@login_required
def logout():
    session.pop('logged_in', None)
    session.pop('user_id', None)
    flash(u'להתראות!')
    return redirect(url_for('notifier.login'))


@notifier.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    form = RegisterForm(request.form)
    if request.method == 'POST':
        if form.validate_on_submit():
            new_user = User(
                form.email.data,
                form.password.data,
            )
            try:
                db.session.add(new_user)
                db.session.commit()
                flash(u'תודה שנרשמת. כעת ניתן להתחבר לאתר')
                return redirect(url_for('notifier.login'))
            except IntegrityError:
                error = 'כתובת הדוא"ל הזו כבר קיימת באתר.'
                return render_template('register.html', form=form, error=error)
    return render_template("register.html", form=form, error=error)


def flash_errors(form):
    for field, errors in form.errors.items():
        for error in errors:
            flash(u"תקלה בשדה %s - %s" % (
                getattr(form, field).label.text, error), 'error')


@notifier.route('/feeds_editor', methods=["GET","POST"])
@login_required
def feeds_editor():
    user_email = session['user_email']
    return render_template('feeds_editor.html', user_email=user_email,
        form=AddFeedForm(request.form),
        feeds=relevant_feeds(),
        parsed_feeds=parse_feeds(relevant_feeds())
        )


@notifier.route('/addfeed/opentaba', methods=['GET'])
def opentaba_feed():
    url = request.args.get('link','')
    relevantfeeds = relevant_feeds_urls()
    if url not in relevantfeeds:
        title = set_title_by_feed(url)
        title = title[1].split(" ")
        try:
            city = request.args.get('city','')
            title.insert(2," "+city+" ")
        except:
            city=" "
        name = " ".join(title)
        a_new_feed = Feed(
            user_id=session['user_id'],
            url = request.args.get('link',''),
            name=name,
            project='תב"ע פתוחה '+city,
        )
        db.session.add(a_new_feed)
        db.session.commit()
        flash(u'ההזנה החדשה נוספה למאגר')
        return redirect(url_for('notifier.feeds_editor'))
    else:
        flash(u'את/ה כבר עוקבים אחרי מקור מידע זה')
        return redirect(url_for('notifier.feeds_editor'))


@notifier.route('/addfeed', methods=['GET', 'POST'])
@login_required
def new_feed():
    error = None
    form = AddFeedForm(request.form)
    if request.method == 'POST':
        url = form.url.data
        name = " ".join(set_title_by_feed(url))
        try:
            project = get_project_by_feed_url(url)
        except:
            pass

        if project==u'תב"ע פתוחה':
            return redirect(url_for('notifier.opentaba_feed', link= url))

        elif form.validate_on_submit():
            a_new_feed = Feed(
                user_id=session['user_id'],
                name=name,
                url=url,
                project=project,
                )
            db.session.add(a_new_feed)
            db.session.commit()
            flash(u'ההזנה החדשה נוספה למאגר')
            return redirect(url_for('notifier.feeds_editor'))

    elif request.method == 'GET':
        if request.args.get('project') == u'תב"ע פתוחה':
            return redirect(url_for('notifier.opentaba_feed',link=request.args.get('link')))

    user_email = session['user_email']
    return render_template('feeds_editor.html',
                          feed_title=set_title_by_feed(form.url.data),
                          feed_url=form.url.data,
                          form=form,
                          feeds=relevant_feeds(),
                          parsed_feeds=parse_feeds(relevant_feeds()),
                          user_email=user_email,
                          )



@notifier.route('/delete_feed/<int:feed_id>/')
@login_required
def delete_feed(feed_id):
    feed_id = feed_id
    db.session.query(Feed).filter_by(id=feed_id).delete()
    db.session.commit()
    flash(u'מקור זה הוסר מהרשימה שלך')
    return redirect(url_for("notifier.feeds_editor"))


@notifier.route('/share')
# check if a bitly shorten url was already made (and shard) - if it was, add 1 to counter, if not, create one
def share_item(service='email',link='',project='',title=''):
    service = request.args.get('service',service)
    full_url = urllib.parse.quote_plus(request.args.get('url',link))
    feed_title = request.args.get('title',title)
    project = request.args.get('project',project)
    locate_link = SharedItem.query.filter_by(full_url=full_url).first()
    if locate_link is not None:   #if it is the first time item/link is shared
        locate_link.add_share()
        bitly_link=locate_link.bitly
        feed_title=locate_link.feed_title
        project=locate_link.project
    else:                          # if item/link was shared before - add one to counter
        bitlyconnection = bitlyapi.Connection(BITLY_USER, BITLY_KEY)
        bitly_link = bitlyconnection.shorten((full_url))['url']
        new_item=SharedItem(full_url=request.parse.unquote(full_url),
                            bitly=bitly_link,
                            project=project,
                            shares_count=1,
                            feed_title=feed_title)
        db.session.add(new_item)

    db.session.commit()    # save changes to db

    return redirect(sharing_services[service].format(project,feed_title,bitly_link))

sharing_services = {
    'facebook': "https://www.facebook.com/sharer/sharer.php?u={2}:{1},{0}",
    'email':"mailto:?&subject={0}: {1}&body={2}",
    'linkedin':"https://www.linkedin.com/shareArticle?mini=true&url={2}&title={0}:{1}&summary=&source=",
    'twitter':"https://twitter.com/home?url={2}:{1},{0}",
    'google': "https://plus.google.com/share?url={2}",
    }
