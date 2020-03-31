import json
import os
import re

from collections import OrderedDict
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from django_form_builder.dynamic_fields import format_field_name, get_fields_types
from django.conf import settings
from django_form_builder.models import DynamicFieldMap, SavedFormContent
from django_form_builder.utils import get_as_dict, set_as_dict
from organizational_area.models import (OrganizationalStructure,
                                        OrganizationalStructureOffice,
                                        OrganizationalStructureOfficeEmployee,)

from . dynamic_form import DynamicForm
from . utils import *
from . validators import *


def _attachment_upload(instance, filename):
    """
    this function has to return the location to upload the file
    """
    folder = instance.get_folder()
    return os.path.join('{}/{}'.format(folder, filename))


class TicketCategory(models.Model):
    """
    Categoria di appartenenza dei Ticket
    Definisce un particolare ambito
    """
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255,
                            blank=False, null=False)
    description = models.TextField(max_length=500, null=True, blank=True)
    created = models.DateTimeField(auto_now=True)
    modified = models.DateTimeField(auto_now=True)
    organizational_structure = models.ForeignKey(OrganizationalStructure,
                                                 on_delete=models.PROTECT)
    organizational_office = models.ForeignKey(OrganizationalStructureOffice,
                                              on_delete=models.SET_NULL,
                                              null=True, blank=True)
    is_active = models.BooleanField(default=False,
                                    help_text=_("Se disabilitato, non sarà "
                                                "visibile in Aggiungi Ticket"))
    show_heading_text = models.BooleanField(_("Mostra agli utenti un testo "
                                              "di accettazione in fase di "
                                              "apertura nuovo ticket"),
                                            default=settings.SHOW_HEADING_TEXT)
    # fields to map roles
    allow_guest = models.BooleanField(_("Accessibile a Ospiti"), default=True)
    allow_user = models.BooleanField(_("Accessibile a {}").format(settings.ORGANIZATION_USER_LABEL), default=True)
    allow_employee = models.BooleanField(_("Accessibile a {}").format(settings.ORGANIZATION_EMPLOYEE_LABEL), default=True)

    # ticket notify
    is_notify = models.BooleanField(_("Ticket di tipo Notifica"),
                                    default=False,
                                    help_text=_("Ticket che viene "
                                                "automaticamente preso "
                                                "in carico"))
    confirm_message_text = models.CharField(_("Messaggio di conferma"),
                                            max_length=255,
                                            blank=True,
                                            null=True,
                                            help_text=_("Es: 'Hai correttamente "
                                                        "confermato la tua partecipazione'. "
                                                        "Apri e chiudi le parentesi graffe "
                                                        "per inserire il codice del ticket. "
                                                        "Lascia vuoto per usare il testo predefinito \"{}\""
                                                        "").format(settings.NEW_TICKET_CREATED_ALERT))

    class Meta:
        unique_together = ("slug", "organizational_structure")
        ordering = ["name"]
        verbose_name = _("Categoria dei Ticket")
        verbose_name_plural = _("Categorie dei Ticket")

    def can_be_deleted(self):
        """
        Ritorna True se è possibile eliminare la categoria
        """
        moduli = TicketCategoryModule.objects.filter(ticket_category=self)
        for modulo in moduli:
            if not modulo.can_be_deleted():
                return False
        return True

    def something_stops_activation(self):
        category_module = TicketCategoryModule.objects.filter(ticket_category=self,
                                                              is_active=True)
        if not self.organizational_office:
            return _("Per attivare la tipologia di richiesta <b>{}</b> è necessario"
                    " assegnare un ufficio di competenza".format(self))
        elif not self.organizational_office.is_active:
            return _("Per attivare la tipologia di richiesta <b>{}</b> è necessario"
                     " attivare l'ufficio <b>{}</b>".format(self,
                                                            self.organizational_office))
        elif not category_module:
            return _("Per attivare la tipologia di richiesta <b>{}</b> è necessario"
                     " attivare un modulo di input".format(self))
        return False

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        folder = '{}/{}/{}/{}'.format(settings.STRUCTURES_FOLDER,
                                      self.organizational_structure.slug,
                                      settings.TICKET_CATEGORIES_FOLDER,
                                      self.slug)
        return folder

    def get_conditions(self, is_printable=False):
        """
        """
        conditions = TicketCategoryCondition.objects.filter(category=self,
                                                            is_active=True)
        if is_printable:
            conditions = conditions.filter(is_printable=True)
        return conditions

    def get_tasks(self, is_active=True):
        tasks = TicketCategoryTask.objects.filter(category=self)
        if is_active:
            tasks = tasks.filter(is_active=True)
        return tasks

    def allowed_to_user(self, user):
        if not user: return False
        if self.allow_guest: return True

        is_employee = user_is_employee(user)
        if is_employee and self.allow_employee:
            return True
        if user_is_in_organization(user) and self.allow_user: return True
        return False

    def __str__(self):
        return '{}'.format(self.name)


class TicketCategoryModule(models.Model):
    """
    Modulo di input per i ticket di una categoria
    """
    name = models.CharField(max_length=255)
    ticket_category = models.ForeignKey(TicketCategory,
                                        on_delete = models.CASCADE)
    created = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created"]
        verbose_name = _("Modulo di Inserimento Ticket")
        verbose_name_plural = _("Moduli di Inserimento Ticket")

    def can_be_deleted(self):
        """
        """
        # if self.is_active: return False
        ticket_collegati = Ticket.objects.filter(input_module=self).first()
        if ticket_collegati: return False
        return True

    def disable_other_modules(self):
        others = TicketCategoryModule.objects.filter(ticket_category=self.ticket_category).exclude(pk=self.pk)
        for other in others:
            other.is_active = False
            other.save(update_fields = ['is_active'])

    def get_form(self,
                 data=None,
                 files=None,
                 remove_filefields=False,
                 remove_datafields=False,
                 show_conditions=False,
                 **kwargs):
        ticket_input_list = self.ticketcategoryinputlist_set.all().order_by('ordinamento')
        # Static method of DynamicFieldMap
        constructor_dict = DynamicFieldMap.build_constructor_dict(ticket_input_list)
        custom_params = {}
        custom_params['show_conditions'] = show_conditions
        custom_params['category_owner'] = self.ticket_category
        custom_params['subject_initial'] = self.ticket_category.name
        custom_params['description_initial'] = self.ticket_category.description
        form = DynamicFieldMap.get_form(DynamicForm,
                                        constructor_dict=constructor_dict,
                                        custom_params=custom_params,
                                        data=data,
                                        files=files,
                                        remove_filefields=remove_filefields,
                                        remove_datafields=remove_datafields)

        return form

    def __str__(self):
        return '{}'.format(self.name)


# Solo gli utenti Amministratori (lato frontend) possono
# definire i Form di inserimento per ogni categoria di ticket
class TicketCategoryInputList(DynamicFieldMap):
    """
    Classe per la generazione dinamica di forms di inserimento ticket
    """
    category_module = models.ForeignKey(TicketCategoryModule,
                                        on_delete=models.CASCADE)

    class Meta:
        verbose_name = _('Modulo di inserimento')
        verbose_name_plural = _('Moduli di inserimento')

    @staticmethod
    def field_exist(module, field_name):
        field = TicketCategoryInputList.objects.filter(category_module=module,
                                                       name__iexact=field_name).first()
        if field: return field_name
        return False


class Ticket(SavedFormContent):
    """
    Ticket
    """
    code = models.CharField(max_length=255, unique=True)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    created = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   related_name='created_by_user')
    input_module = models.ForeignKey(TicketCategoryModule,
                                     on_delete=models.PROTECT)
    # is_taken = models.BooleanField(default=False)
    # taken_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 # on_delete=models.SET_NULL,
                                 # null=True, blank=True,
                                 # related_name='taken_by_user')
    is_closed = models.BooleanField(default=False)
    closed_date = models.DateTimeField(blank=True, null=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                  on_delete=models.SET_NULL,
                                  null=True, blank=True,
                                  related_name='closed_by_user')
    closing_reason = models.TextField(blank=True, null=True)
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ["is_closed",
                    "priority",
                    # "is_taken",
                    "-created",
                    "code"]
        verbose_name = _("Ticket")
        verbose_name_plural = _("Ticket")

    def save(self, *args, **kwargs):
        if len(self.modulo_compilato) > settings.TICKET_MIN_DIGITS_TO_COMPRESS:
            self.modulo_compilato = compress_text_to_b64(self.modulo_compilato).decode()
        super().save(*args, **kwargs)

    def get_category(self):
        return self.input_module.ticket_category

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        folder = '{}/{}/{}'.format(settings.TICKET_ATTACHMENT_FOLDER,
                                   self.get_year(),
                                   self.code)
        return folder

    def get_modulo_compilato(self):
        try:
            json_dict = json.loads(decompress_text(self.modulo_compilato))
        except:
            json_dict = json.loads(self.modulo_compilato)
        return json_dict

    @staticmethod
    def get_user_ticket_per_day(user, date=None):
        """
        """
        dt = date if date else timezone.now().date()
        tickets = Ticket.objects.filter(created_by=user,
                                        created__contains=dt)
        return tickets

    def get_url(self, structure=None):
        """
        if structure is present means that the requested url is for
        management
        """
        if structure:
            return reverse('uni_ticket:manage_ticket_url_detail', kwargs={'ticket_id': self.code,
                                                                          'structure_slug': structure.slug})

        return reverse('uni_ticket:ticket_detail', kwargs={'ticket_id': self.code})

    @staticmethod
    def number_limit_reached_by_user(user):
        """
        """
        if settings.MAX_DAILY_TICKET_PER_USER == 0: return False
        today_tickets = Ticket.get_user_ticket_per_day(user=user).count()
        if today_tickets < settings.MAX_DAILY_TICKET_PER_USER: return False
        return True


    def get_year(self):
        """
        """
        return self.created.year

    def is_open(self, user=None):
        if self.is_closed: return False
        if not self.has_been_taken(user=user): return False
        return True

    def check_if_owner(self, user):
        """
        Ritorna True se l'utente passato come argomento ha creato il ticket
        """
        if not user: return False
        if user == self.created_by: return True

    def get_allegati_dict(self, ticket_dict={}):
        allegati_dict = {}
        if ticket_dict:
            allegati_dict = ticket_dict.get(settings.ATTACHMENTS_DICT_PREFIX)
        else:
            # json_dict = json.loads(self.get_modulo_compilato())
            json_dict = self.get_modulo_compilato()
            allegati_dict = get_as_dict(compiled_module_json=json_dict).get(settings.ATTACHMENTS_DICT_PREFIX)
        return allegati_dict

    def get_form_module(self):
        """
        Ritorna il modulo di input con cui il ticket è stato compilato
        """
        return self.input_module

    def compiled_form(self, files=None,
                      remove_filefields=True,
                      remove_datafields=False):
        """
        Torna il form compilato senza allegati
        """
        modulo = self.get_form_module()
        if not modulo: return None
        extra_datas = {}
        extra_datas[settings.TICKET_SUBJECT_ID] = self.subject
        extra_datas[settings.TICKET_DESCRIPTION_ID] = self.description
        form = SavedFormContent.compiled_form(data_source=json.dumps(self.get_modulo_compilato()),
                                              extra_datas=extra_datas,
                                              files=files,
                                              remove_filefields=remove_filefields,
                                              remove_datafields=remove_datafields,
                                              form_source=modulo)
        return form

    def save_data(self, subject, description, ticket_dict):
        self.subject = subject
        self.description = description
        set_as_dict(self, ticket_dict,
                    fields_to_pop=[settings.TICKET_SUBJECT_ID,
                                   settings.TICKET_DESCRIPTION_ID])

    def get_status(self):
        if self.is_closed:
            if self.input_module.ticket_category.is_notify:
                return _('<b class="text-success">Chiuso</b>')
            return _('<b class="text-success">Chiuso</b> <small>[{}]</small>').format(self.closed_by)
        if not self.has_been_taken(): return _('<b class="text-danger">Aperto</b>')
        return _('<b class="text-warning">Assegnato</b> {}').format(self.taken_by_list())

    def update_log(self, user, note='', send_mail=True, mail_msg=''):
        if not user: return False
        if send_mail:
            # Send mail to ticket owner
            d = {'hostname': settings.HOSTNAME,
                 'user': user,
                 'message': mail_msg or note,
                 'ticket': self
                }
            m_subject = _('{} - ticket {} aggiornato'.format(settings.HOSTNAME,
                                                             self))
            # Start send mail to ticket owner
            send_custom_mail(subject=m_subject,
                             recipient=self.created_by,
                             body=settings.TICKET_UPDATED,
                             params=d)
            # End send mail to ticket owner

        LogEntry.objects.log_action(user_id         = user.pk,
                                    content_type_id = ContentType.objects.get_for_model(self).pk,
                                    object_id       = self.pk,
                                    object_repr     = self.__str__(),
                                    action_flag     = CHANGE,
                                    change_message  = note)

    def get_assigned_to_offices(self,
                                office_active=True,
                                structure=None,
                                ignore_follow=True):
        """
        Returns to wicth offices ticket is assigned
        """
        assignments = TicketAssignment.objects.filter(ticket=self)
        if not ignore_follow:
            assignments = assignments.filter(follow=True)
        offices = []
        for assignment in assignments:
            office = assignment.office
            if structure and not office.organizational_structure==structure:
                continue
            if not office_active: offices.append(office)
            elif office.is_active: offices.append(office)
        return offices

    def get_assigned_to_structures(self, ignore_follow=True):
        """
        Returns to wich structures ticket is assigned
        """
        offices = self.get_assigned_to_offices(office_active=False,
                                               ignore_follow=ignore_follow)
        structures = []
        for office in offices:
            struct = office.organizational_structure
            if struct not in structures:
                structures.append(struct)
        return structures

    def add_competence(self, office, user, note=None):
        """
        Aggiunge un nuovo ufficio di competenza per la gestione
        del ticket
        """
        competence = TicketAssignment.objects.filter(ticket=self,
                                                     office=office).first()
        if competence: return False
        new_competence = TicketAssignment(ticket=self,
                                          office=office,
                                          note=note,
                                          assigned_by=user)

        # if user that transfer competence is a destination office operator
        # he takes competence in destination office
        if OrganizationalStructureOfficeEmployee.objects.filter(employee=user, office=office):
            new_competence.taken_by = user
            new_competence.taken_date = timezone.now()

        new_competence.save()
        return new_competence

    def block_competence(self, user, structure, allow_readonly=True):
        """
        """
        usertype = get_user_type(user, structure)
        if usertype == 'user': return False
        # offices = []
        offices = self.get_assigned_to_offices(office_active=False,
                                               structure=structure)
        offices_to_disable = []
        if usertype == 'operator':
            for office in offices:
                # default office can't be unassigned
                if office.is_default: continue
                office_employee = OrganizationalStructureOfficeEmployee.objects.filter(employee=user,
                                                                                       office=office)
                if office_employee:
                    offices_to_disable.append(office)
        elif usertype == 'manager': offices_to_disable = offices
        for off in offices_to_disable:
            # default office can't be unassigned
            if off.is_default: continue
            competence = TicketAssignment.objects.get(ticket=self,
                                                      office=off,
                                                      taken_date__isnull=False)
            if not competence.follow: continue
            competence.follow = allow_readonly
            competence.readonly = allow_readonly
            competence.save(update_fields = ['follow',
                                             'modified',
                                             'readonly'])
        return offices_to_disable

    def get_dependences(self):
        """
        """
        # dependences = []
        t2t_list = Ticket2Ticket.objects.filter(slave_ticket=self).all()
        # for t2t in t2t_list:
            # dependences.append(t2t.master_ticket)
        # return dependences
        return t2t_list

    def get_task(self):
        """
        """
        task = []
        ticket_task = Task.objects.filter(ticket=self).all()
        for t in ticket_task:
            task.append(t)
        return task

    def blocks_some_ticket(self):
        """
        """
        dependences = []
        t2t_list = Ticket2Ticket.objects.filter(master_ticket=self).all()
        for t2t in t2t_list:
            dependences.append(t2t.slave_ticket)
        return dependences

    def is_closable(self):
        """
        """
        if not self.has_been_taken(): return False
        if self.is_closed: return False
        dependences = self.get_dependences()
        task_list = self.get_task()
        if not dependences and not task_list: return True
        for dependence in dependences:
            if not dependence.master_ticket.is_closed: return False
        for task in task_list:
            if not task.is_closed: return False
        return True

    def is_valid(self):
        """
        """
        json_dict = self.get_modulo_compilato()
        ticket_dict = get_as_dict(json_dict)
        if not settings.ATTACHMENTS_DICT_PREFIX in ticket_dict: return True
        allegati = ticket_dict.get(settings.ATTACHMENTS_DICT_PREFIX)
        # valido solo i campi File vuoti del form
        # evito di validare tutti gli altri campi, sicuramente corretti
        form = self.compiled_form(files=None,
                                  remove_filefields=allegati,
                                  remove_datafields=True)
        if form.is_valid(): return True
        return False

    def get_priority(self):
        """
        """
        return dict(settings.PRIORITY_LEVELS).get(str(self.priority))

    def get_messages_count(self, by_operator=False):
        all_messages = TicketReply.objects.filter(ticket=self)
        first_created = all_messages.first()
        # If I'm a manager/operator
        unread_messages = all_messages.filter(read_date=None)
        # if I'm a simple user, I want my agents replies
        if by_operator:
            unread_messages = unread_messages.exclude(structure=None)
        else:
            unread_messages = unread_messages.filter(structure=None)
        return (all_messages.count(),
                unread_messages.count(),
                first_created.created if first_created else None)

    def _check_assignment_privileges(self, queryset):
        if not queryset: return False
        if queryset.filter(readonly=False):
            readonly_value = False
        elif queryset.filter(readonly=True):
            readonly_value = True
        d = {'follow': True,
             'readonly': readonly_value}
        return d
        # return json.loads(d)

    def is_followed_in_structure(self, structure):
        if not structure: return False
        assignment = TicketAssignment.objects.filter(ticket=self,
                                                     office__organizational_structure=structure,
                                                     office__is_active=True,
                                                     follow=True)
        return self._check_assignment_privileges(assignment)

    def is_followed_by_office(self, office):
        if not office: return False
        assignment = TicketAssignment.objects.filter(ticket=self,
                                                     office=office,
                                                     office__is_active=True,
                                                     follow=True)
        return self._check_assignment_privileges(assignment)

    def is_followed_by_one_of_offices(self, offices):
        if not offices: return False
        assignment = TicketAssignment.objects.filter(ticket=self,
                                                     office__in=offices,
                                                     follow=True)
        return self._check_assignment_privileges(assignment)

    def has_been_taken(self, user=None):
        assignments = TicketAssignment.objects.filter(ticket=self)
        if not assignments.first(): return False
        if not assignments.first().taken_date: return False
        if not user: return True
        for assignment in assignments:
            if assignment.taken_date and user_manage_office(user, assignment.office):
                return True
        return False

    def taken_by_list(self):
        office_operators = {}
        assignments = TicketAssignment.objects.filter(ticket=self)
        result = '<ul>'
        for assignment in assignments:
            assigned = assignment.taken_by or _("Da assegnare")
            result = '{}<li><small><b>{}</b></small>: <small>{}</small></li>'.format(result,
                                                   assignment.office,
                                                   assigned)
            # office_operators[assignment.office.__str__()] = assigned.__str__()
        return '{}</ul>'.format(result)

    def take(self, user, assigned_by=None):
        assignments = TicketAssignment.objects.filter(ticket=self)
        for assignment in assignments:
            if user_manage_office(user, assignment.office) and not assignment.taken_date:
                assignment.taken_date = timezone.now()
                assignment.taken_by = user
                if assigned_by:
                    assignment.assigned_by = assigned_by
                    assignment.created = timezone.now()
                assignment.save()

    def is_untaken_by_user_offices(self, user):
        assignments = TicketAssignment.objects.filter(ticket=self)
        offices = []
        for assignment in assignments:
            if user_manage_office(user, assignment.office) and not assignment.taken_date:
                offices.append(assignment.office)
        return offices

    def __str__(self):
        return '{} ({})'.format(self.subject, self.code)


class TicketAssignment(models.Model):
    """
    Ufficio di competenza per la gestione Ticket
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    office = models.ForeignKey(OrganizationalStructureOffice,
                               on_delete=models.PROTECT)
    created = models.DateTimeField(auto_now=True)
    modified = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True, null=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.PROTECT,
                                    null=True)
    taken_date = models.DateTimeField(null=True, blank=True)
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.PROTECT,
                                 null=True, blank=True,
                                 related_name='taken_by_operator')
    follow = models.BooleanField(default=True)
    readonly = models.BooleanField(default=False)

    class Meta:
        unique_together = ("ticket", "office")
        ordering = ["created"]
        verbose_name = _("Competenza Ticket")
        verbose_name_plural = _("Competenza Ticket")

    @staticmethod
    def get_ticket_per_structure(structure, follow_check=True):
        """
        """
        offices = OrganizationalStructureOffice.objects.filter(organizational_structure=structure,
                                                               is_active = True)
        ticket_assignments = TicketAssignment.objects.filter(office__in=offices)
        ticket_list = []
        for assignment in ticket_assignments:
            if follow_check and not assignment.follow: continue
            ticket = assignment.ticket
            if ticket.code not in ticket_list:
                ticket_list.append(ticket.code)
        return ticket_list

    @staticmethod
    def get_ticket_in_office_list(office_list, follow_check=True):
        """
        """
        ticket_assignments = TicketAssignment.objects.filter(office__in=office_list,
                                                             office__is_active=True)
        ticket_list = []
        for assignment in ticket_assignments:
            if follow_check and not assignment.follow: continue
            ticket = assignment.ticket
            if ticket.code not in ticket_list:
                ticket_list.append(ticket.code)
        return ticket_list

    def __str__(self):
        return '{} - {}'.format(self.ticket, self.office)


class TicketReply(models.Model):
    """
    Cronologia Domande/Riposte utente-agente
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.PROTECT)
    structure = models.ForeignKey(OrganizationalStructure,
                                  on_delete=models.SET_NULL,
                                  null=True, blank=True)
    subject = models.CharField(max_length=255)
    text = models.TextField()
    attachment = models.FileField(upload_to=_attachment_upload,
                                  null=True, blank=True,
                                  validators=[validate_file_extension,
                                              validate_file_size,
                                              validate_file_length])
    created = models.DateTimeField(auto_now=True)
    read_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                on_delete=models.SET_NULL,
                                null=True, blank=True,
                                related_name='ticket_replies_read_by')
    read_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["ticket", "created"]
        verbose_name = _("Domande/Risposte Ticket")
        verbose_name_plural = _("Domande/Risposte Ticket")

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        ticket_folder = self.ticket.get_folder()
        folder = '{}/{}'.format(ticket_folder,
                                settings.TICKET_MESSAGES_ATTACHMENT_SUBFOLDER)
        return folder

    def __str__(self):
        return '{} - {}'.format(self.subject, self.ticket)


class Ticket2Ticket(models.Model):
    """
    Dipendenza Ticket da altri Ticket
    Lo Slave non può essere chiuso se ci sono Master da risolvere
    """
    slave_ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE,
                                     related_name="master")
    master_ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE,
                                      related_name="slave")
    note = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("slave_ticket", "master_ticket")
        ordering = ["slave_ticket", "master_ticket"]
        verbose_name = _("Dipendenza Ticket")
        verbose_name_plural = _("Dipendenze Ticket")

    @staticmethod
    def master_is_already_used(ticket):
        """
        """
        relations = Ticket2Ticket.objects.filter(slave_ticket=ticket)
        if not relations: return False
        for relation in relations:
            master = relation.master_ticket
            if not master.is_closed: return True
        return False

    def __str__(self):
        return '{} - {}'.format(self.slave_ticket, self.master_ticket)


class AbstractTask(models.Model):
    """
    """
    subject = models.CharField(max_length=255)
    code = models.CharField(max_length=255, unique=True)
    description = models.TextField()
    created = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL,
                                   null=True)
    priority = models.IntegerField(default=0)
    attachment = models.FileField(upload_to=_attachment_upload,
                                  null=True, blank=True,
                                  validators=[validate_file_extension,
                                              validate_file_size,
                                              validate_file_length])

    class Meta:
        abstract = True

    def get_priority(self):
        """
        """
        return dict(settings.PRIORITY_LEVELS).get(str(self.priority))


class Task(AbstractTask):
    """
    ToDo interno alla Struttura che può essere vincolante se associato
    a un Ticket (il Ticket non può essere chiuso se il task non è chiuso)
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    is_closed = models.BooleanField(default=False)
    closed_date = models.DateTimeField(blank=True, null=True)
    closing_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["created"]
        verbose_name = _("Task")
        verbose_name_plural = _("Task")

    def update_log(self, user, note=None):
        LogEntry.objects.log_action(user_id         = user.pk,
                                    content_type_id = ContentType.objects.get_for_model(self).pk,
                                    object_id       = self.pk,
                                    object_repr     = self.__str__(),
                                    action_flag     = CHANGE,
                                    change_message  = note)

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        ticket_folder = self.ticket.get_folder()
        folder = '{}/{}/{}'.format(ticket_folder,
                                   settings.TICKET_TASK_ATTACHMENT_SUBFOLDER,
                                   self.code)
        return folder

    def __str__(self):
        return '{} - ticket: {}'.format(self.subject, self.ticket)


class Task2Ticket(models.Model):
    """
    Dipendenza Ticket da Task
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT)
    task = models.ForeignKey(Task, on_delete=models.PROTECT)
    # User o Employee?
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL,
                                   null=True)

    class Meta:
        unique_together = ("ticket", "task")
        ordering = ["task", "ticket"]
        verbose_name = _("Dipendenza Ticket da Task")
        verbose_name_plural = _("Dipendenze Ticket da Task")

    def __str__(self):
        return '{} - {}'.format(self.task, self.ticket)


class TicketCategoryCondition(models.Model):
    """
    """
    category = models.ForeignKey(TicketCategory, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=False, null=False)
    text = models.TextField(blank=False, null=False)
    ordinamento = models.PositiveIntegerField(blank=True, default=0)
    attachment = models.FileField(upload_to=_attachment_upload,
                                  null=True, blank=True,
                                  validators=[validate_file_extension,
                                              validate_file_size,
                                              validate_file_length])
    is_printable = models.BooleanField(_('Visibile nella versione stampabile'),
                                       default=False)
    is_active = models.BooleanField(_('Visibile agli utenti'), default=True)

    class Meta:
        ordering = ('ordinamento', )
        verbose_name = _('Clausola tipologia di richiesta ticket')
        verbose_name_plural = _('Clausole tipologia di richiesta ticket')

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        category_folder = self.category.get_folder()
        return '{}/{}'.format(category_folder,
                              settings.CATEGORY_CONDITIONS_ATTACHMENT_SUBFOLDER)

    def corpo_as_html(self):
        return text_as_html(self.text)

    def __str__(self):
        return '({}) {}'.format(self.category, self.title)


class TicketCategoryTask(AbstractTask):
    """
    ToDo interno alla Struttura che può essere vincolante se associato
    a un Ticket (il Ticket non può essere chiuso se il task non è chiuso)
    """
    category = models.ForeignKey(TicketCategory, on_delete=models.CASCADE)
    is_active = models.BooleanField(_('Visibile nei ticket'),
                                    default=False)

    class Meta:
        ordering = ["created"]
        verbose_name = _("Task predefinito")
        verbose_name_plural = _("Task predefiniti")

    def get_folder(self):
        """
        Returns ticket attachments folder path
        """
        category_folder = self.category.get_folder()
        folder = '{}/{}/{}'.format(category_folder,
                                   settings.TICKET_TASK_ATTACHMENT_SUBFOLDER,
                                   self.code)
        return folder

    def __str__(self):
        return '{} - {}'.format(self.subject, self.category)
