import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, HttpResponseRedirect
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.html import escape, strip_tags
from django.utils.text import slugify
from django.utils.translation import gettext as _

from django_form_builder.utils import get_labeled_errors
from organizational_area.models import *
from uni_ticket.decorators import (has_access_to_ticket,
                                   is_manager,
                                   ticket_assigned_to_structure,
                                   ticket_is_not_taken_and_not_closed)
from uni_ticket.forms import *
from uni_ticket.models import *
from uni_ticket.utils import (custom_message,
                              office_can_be_deleted,
                              user_is_manager)


logger = logging.getLogger(__name__)


@login_required
@is_manager
def dashboard(request, structure_slug, structure):
    """
    Manager Dashboard

    :type structure_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _("Pannello di Controllo")
    sub_title = _("Gestisci ticket per la struttura {}").format(structure)
    template = "manager/dashboard.html"

    ta = TicketAssignment
    structure_tickets = ta.get_ticket_per_structure(structure=structure)
    tickets = Ticket.objects.filter(code__in=structure_tickets)
    non_gestiti = tickets.filter(is_taken=False,
                                 is_closed=False)
    aperti = tickets.filter(is_taken=True, is_closed=False)
    chiusi = tickets.filter(is_closed=True)

    om = OrganizationalStructureOffice
    offices = om.objects.filter(organizational_structure=structure)

    cm = TicketCategory
    categories = cm.objects.filter(organizational_structure=structure)

    messages = 0
    for ticket in tickets:
        if not ticket.is_followed_in_structure(structure=structure):
            continue
        messages += ticket.get_messages_count()[1]

    d = {'ticket_messages': messages,
         'categories': categories,
         'offices': offices,
         'structure': structure,
         'sub_title': sub_title,
         'ticket_aperti': aperti,
         'ticket_chiusi': chiusi,
         'ticket_non_gestiti': non_gestiti,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def offices(request, structure_slug, structure):
    """
    Retrieves structure offices list

    :type structure_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Gestione uffici')
    template = 'manager/offices.html'
    os = OrganizationalStructureOffice
    offices = os.objects.filter(organizational_structure=structure)

    d = {'offices': offices,
         'structure': structure,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def office_add_new(request, structure_slug, structure):
    """
    Adds new office to structure

    :type structure_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Nuovo ufficio')
    sub_title = _("Crea un nuovo ufficio nella struttura {}").format(structure)
    form = OfficeForm()
    if request.method == 'POST':
        form = OfficeForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            slug = slugify(name)
            os = OrganizationalStructureOffice
            slug_name_exist = os.objects.filter(Q(name=name) | Q(slug=slug),
                                                organizational_structure=structure)
            if slug_name_exist:
                messages.add_message(request, messages.ERROR,
                                     _("Esiste già un ufficio con"
                                     " nome {} o slug {}".format(name, slug)))
            else:
                new_office = form.save(commit=False)
                new_office.slug = slug
                new_office.organizational_structure = structure
                new_office.save()

                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} created new office {}'.format(timezone.now(),
                                                               structure,
                                                               request.user,
                                                               new_office))

                messages.add_message(request, messages.SUCCESS,
                                     _("Ufficio creato con successo"))
                return redirect('uni_ticket:manager_office_detail',
                                structure_slug=structure_slug,
                                office_slug=new_office.slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "{}: {}".format(k, strip_tags(v)))
    template = 'manager/office_add_new.html'
    d = {'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def office_edit(request, structure_slug, office_slug, structure):
    """
    Edits office details

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)

    title = _('Modifica ufficio')
    sub_title = office.name

    form = OfficeForm(instance=office)
    if request.method == 'POST':
        form = OfficeForm(instance=office, data=request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            slug = slugify(name)
            oso = OrganizationalStructureOffice
            slug_name_exist = oso.objects.filter(Q(name=name) | Q(slug=slug),
                                                 organizational_structure=structure).exclude(pk=office.pk)
            if slug_name_exist:
                messages.add_message(request, messages.ERROR,
                                 _("Esiste già un ufficio con questo"
                                   " nome o slug"))
            else:
                edited_office = form.save(commit=False)
                edited_office.slug = slug
                edited_office.save()
                messages.add_message(request, messages.SUCCESS,
                                     _("Ufficio modificato con successo"))

                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} edited office {}'.format(timezone.now(),
                                                          structure,
                                                          request.user,
                                                          edited_office))

                return redirect('uni_ticket:manager_office_detail',
                                structure_slug=structure_slug,
                                office_slug=edited_office.slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    template = 'manager/office_edit.html'
    d = {'form': form,
         'office': office,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def office_detail(request, structure_slug, office_slug, structure):
    """
    Views office details

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    title = _('Gestione ufficio')
    template = 'manager/office_detail.html'
    sub_title = office.name
    form = OfficeAddOperatorForm(structure=structure,
                                 office_slug=office_slug,
                                 current_user=request.user)
    category_form = OfficeAddCategoryForm(structure=structure,
                                          office=office)
    if request.method == 'POST':
        form = OfficeAddOperatorForm(request.POST,
                                     structure=structure)

        if form.is_valid():
            employee = form.cleaned_data['operatore']
            description = form.cleaned_data['description']
            oso = OrganizationalStructureOfficeEmployee
            new_officeemployee = oso(employee=employee,
                                     office=office,
                                     description=description)
            new_officeemployee.save()
            messages.add_message(request, messages.SUCCESS,
                                 _("Operatore assegnato con successo"))

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} added employe {}'
                        ' to office {}'.format(timezone.now(),
                                               structure,
                                               request.user,
                                               employee,
                                               office))

            return redirect('uni_ticket:manager_office_detail',
                            structure_slug=structure_slug,
                            office_slug=office_slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    em = OrganizationalStructureOfficeEmployee
    employees = em.objects.filter(office=office,
                                  employee__is_active=True)
    d = {'category_form': category_form,
         'employees': employees,
         'form': form,
         'office': office,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def office_add_category(request, structure_slug, office_slug, structure):
    """
    Assings new category to office competences

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    if request.method == 'POST':
        office = get_object_or_404(OrganizationalStructureOffice,
                                   organizational_structure=structure,
                                   slug=office_slug)
        form = OfficeAddCategoryForm(request.POST,
                                     structure=structure,
                                     office=office)
        if form.is_valid():
            category = form.cleaned_data['category']
            if category.organizational_office:
                messages.add_message(request, messages.ERROR,
                                     _("Il tipo di richiesta <b>{}</b> risulta "
                                       "già assegnato all'ufficio <b>{}</b>. "
                                       "Rimuovere la competenza per "
                                       "procedere").format(category,
                                                           category.organizational_office))
                return redirect('uni_ticket:manager_office_detail',
                                structure_slug=structure_slug,
                                office_slug=office_slug)
            category.organizational_office = office
            category.save(update_fields = ['organizational_office'])
            messages.add_message(request, messages.SUCCESS,
                                 _("Competenza ufficio impostata con successo"))

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} added category {}'
                        ' to office {}'.format(timezone.now(),
                                                 structure,
                                                 request.user,
                                                 category,
                                                 office))

        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
        return redirect('uni_ticket:manager_office_detail',
                        structure_slug=structure_slug,
                        office_slug=office_slug)
    return custom_message(request, _("Impossibile accedere a questo URL "
                                     "senza passare dal form collegato."),
                          structure_slug=structure.slug)

@login_required
@is_manager
def office_remove_category(request, structure_slug,
                           office_slug, category_slug, structure):
    """
    Remove category from office competences

    :type structure_slug: String
    :type office_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)

    if category.organizational_office != office:
        messages.add_message(request, messages.ERROR,
                             _("Il tipo di richiesta non è di competenza di"
                               " questo ufficio"))
    else:
        category.organizational_office = None
        category.is_active = False
        category.save(update_fields = ['organizational_office', 'is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Il tipo di richiesta <b>{}</b> non è più di competenza "
                               " dell'ufficio <b>{}</b> ed è stato disattivato".format(category,
                                                                                       office)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} removed category {}'
                    ' from office {}'.format(timezone.now(),
                                             structure,
                                             request.user,
                                             category,
                                             office))

    return redirect('uni_ticket:manager_office_detail',
                    structure_slug=structure_slug,
                    office_slug=office_slug)

@login_required
@is_manager
def office_remove_operator(request, structure_slug,
                           office_slug, employee_id, structure):
    """
    Remove employee from office

    :type structure_slug: String
    :type office_slug: String
    :type employee_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param employee_id: employee_id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    user_model = get_user_model()
    employee = user_model.objects.get(pk=employee_id)
    usertype = get_user_type(employee, structure)
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)

    # Try to delete manager user from help-desk office (default)
    if usertype == 'manager' and office.is_default:
        return custom_message(request, _("Eliminando l'afferenza dell'utente"
                                         " a questo ufficio, egli perderà i"
                                         " privilegi di Amministratore."
                                         " Questa operazione, pertanto,"
                                         " non può essere eseguita in autonomia."
                                         " Contattare l'assistenza tecnica."),
                              structure_slug=structure.slug)
    m = OrganizationalStructureOfficeEmployee
    office_employee = m.objects.get(office=office,
                                    employee=employee)
    if not office_employee:
        messages.add_message(request, messages.ERROR,
                             _("L'operatore non è assegnato a questo ufficio"))
    else:
        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} removed employee {}'
                    ' from office {}'.format(timezone.now(),
                                             structure,
                                             request.user,
                                             employee,
                                             office))
        office_employee.delete()
        messages.add_message(request, messages.SUCCESS,
                             _("Operatore {} rimosso correttamente".format(employee)))
    return redirect('uni_ticket:manager_office_detail',
                    structure_slug=structure_slug,
                    office_slug=office_slug)

@login_required
@is_manager
def office_disable(request, structure_slug, office_slug, structure):
    """
    Disables an office

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    one_tickets_for_this_office = False
    office_tickets = TicketAssignment.objects.filter(office=office,
                                                     # ticket__is_closed=False,
                                                     follow=True)
    one_tickets_for_this_office = False
    for ot in office_tickets:
        other_offices_for_ticket = TicketAssignment.objects.filter(office__is_active=True,
                                                                   ticket=ot.ticket).exclude(office=office)
        if not other_offices_for_ticket:
            one_tickets_for_this_office = True
            break

    if office.is_default:
        messages.add_message(request, messages.ERROR,
                             _("Impossibile disattivare questo ufficio"))
    elif one_tickets_for_this_office:
        messages.add_message(request, messages.ERROR,
                             _("Impossibile disattivare questo ufficio."
                               " Alcuni ticket potrebbero rimanere privi di gestione"))
    elif office.is_active:
        assigned_categories = TicketCategory.objects.filter(organizational_office=office)
        for cat in assigned_categories:
            cat.is_active = False
            cat.save(update_fields = ['is_active'])
            messages.add_message(request, messages.SUCCESS,
                                 _("Categoria {} disattivata correttamente".format(cat)))
        office.is_active = False
        office.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Ufficio {} disattivato con successo".format(office)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} disabled office {}'.format(timezone.now(),
                                                    structure,
                                                    request.user,
                                                    office))

    else:
        messages.add_message(request, messages.ERROR,
                             _("Ufficio {} già disattivato".format(office)))
    return redirect('uni_ticket:manager_office_detail',
                    structure_slug=structure_slug,
                    office_slug=office_slug)

@login_required
@is_manager
def office_enable(request, structure_slug, office_slug, structure):
    """
    Enables an office

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    if office.is_active:
        messages.add_message(request, messages.ERROR,
                             _("Ufficio {} già attivato".format(office)))
    else:
        office.is_active = True
        office.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Ufficio {} attivato con successo".format(office)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} enabled office {}'.format(timezone.now(),
                                                  structure,
                                                  request.user,
                                                  office))

    return redirect('uni_ticket:manager_office_detail',
                    structure_slug=structure_slug,
                    office_slug=office_slug)

@login_required
@is_manager
def office_delete(request, structure_slug, office_slug, structure):
    """
    Deletes an office

    :type structure_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    if office_can_be_deleted(office):
        assigned_categories = TicketCategory.objects.filter(organizational_office=office)
        for cat in assigned_categories:
            cat.is_active = False
            cat.save(update_fields = ['is_active'])
            messages.add_message(request, messages.SUCCESS,
                                 _("Categoria {} disattivata correttamente".format(cat)))
        messages.add_message(request, messages.SUCCESS,
                             _("Ufficio {} eliminato correttamente".format(office)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} deleted office {}'.format(timezone.now(),
                                                   structure,
                                                   request.user,
                                                   office))

        office.delete()
        return redirect('uni_ticket:manager_dashboard', structure_slug=structure_slug)
    messages.add_message(request, messages.ERROR,
                         _("Impossibile eliminare l'ufficio {}."
                           " Ci sono ticket assegnati"
                           " o è l'ufficio predefinito della struttura.".format(office)))
    return redirect('uni_ticket:manager_office_detail',
                    structure_slug=structure_slug,
                    office_slug=office_slug)

@login_required
@is_manager
def category_detail(request, structure_slug, category_slug, structure):
    """
    Shows category details

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    title = _('Gestione tipo di richiesta')
    template = 'manager/category_detail.html'
    sub_title = category
    form = CategoryAddOfficeForm(structure=structure)
    if request.method == 'POST':
        if category.organizational_office:
            messages.add_message(request, messages.ERROR,
                                 _("Competenza ufficio già presente"))
            return redirect('uni_ticket:manager_category_detail',
                            structure_slug=structure_slug,
                            category_slug=category_slug)
        form = CategoryAddOfficeForm(request.POST,
                                     structure=structure)
        if form.is_valid():
            office = form.cleaned_data['office']
            category.organizational_office = office
            category.save(update_fields = ['organizational_office'])
            messages.add_message(request, messages.SUCCESS,
                                 _("Competenza ufficio impostata con successo"))
            return redirect('uni_ticket:manager_category_detail',
                            structure_slug=structure_slug,
                            category_slug=category_slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    d = {'category': category,
         'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_remove_office(request, structure_slug,
                           category_slug, office_slug, structure):
    """
    Remove office competence from category

    :type structure_slug: String
    :type category_slug: String
    :type office_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param office_slug: office slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    office = get_object_or_404(OrganizationalStructureOffice,
                               organizational_structure=structure,
                               slug=office_slug)
    if category.organizational_office != office:
        messages.add_message(request, messages.ERROR,
                             _("Il tipo di richiesta non è di competenza di"
                               " questo ufficio"))
    else:
        category.organizational_office = None
        category.is_active = False
        category.save(update_fields = ['is_active', 'organizational_office'])
        messages.add_message(request, messages.SUCCESS,
                             _("Competenza ufficio {} rimossa correttamente".format(office)))
        messages.add_message(request, messages.ERROR,
                             _("Tipo di richieste {} disattivato poichè"
                               " priva di ufficio competente".format(category)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} removed office {}'
                    ' from category {}'
                    ' (now disabled)'.format(timezone.now(),
                                             structure,
                                             request.user,
                                             office,
                                             category))

    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_add_new(request, structure_slug, structure):
    """
    Adds new category

    :type structure_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Nuovo tipo di richiesta')
    sub_title = _("Crea un nuovo tipo di richiesta nella struttura {}").format(structure)
    form = CategoryForm()
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            slug = slugify(name)
            m = TicketCategory
            slug_name_exist = m.objects.filter(Q(name=name) | Q(slug=slug),
                                               organizational_structure=structure)
            if slug_name_exist:
                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} tried to add a new category'
                            ' with existent name {} or slug {}'.format(timezone.now(),
                                                                       structure,
                                                                       request.user,
                                                                       name,
                                                                       slug))
                messages.add_message(request, messages.ERROR,
                                 _("Esiste già un tipo di richiesta con"
                                   " nome {} o slug {}".format(name, slug)))
            else:
                new_category = form.save(commit=False)
                new_category.slug = slug
                new_category.organizational_structure = structure
                new_category.save()
                messages.add_message(request, messages.SUCCESS,
                                     _("Categoria creata con successo"))

                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} added a new category'
                            ' with name {} and slug {}'.format(timezone.now(),
                                                               structure,
                                                               request.user,
                                                               name,
                                                               slug))

                return redirect('uni_ticket:manager_category_detail',
                                structure_slug=structure_slug,
                                category_slug=new_category.slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    template = 'manager/category_add_new.html'
    d = {'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_edit(request, structure_slug, category_slug, structure):
    """
    Edits category details

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    form = CategoryForm(instance=category)
    if request.method == 'POST':
        form = CategoryForm(instance=category, data=request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            slug = slugify(name)
            slug_name_exist = TicketCategory.objects.filter(Q(name=name) | Q(slug=slug),
                                                            organizational_structure=structure).exclude(pk=category.pk)
            if slug_name_exist:
                messages.add_message(request, messages.ERROR,
                                 _("Esiste già un tipo di richiesta con questo"
                                   " nome o slug"))
            else:
                edited_category = form.save(commit=False)
                edited_category.slug = slug
                edited_category.save(update_fields = ['name', 'slug',
                                                      'description',
                                                      'show_heading_text',
                                                      'allow_guest',
                                                      'allow_user',
                                                      'allow_employee',
                                                      'modified'])
                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} edited the category {}'.format(timezone.now(),
                                                                structure,
                                                                request.user,
                                                                category))

                messages.add_message(request, messages.SUCCESS,
                                     _("Categoria modificata con successo"))
                return redirect('uni_ticket:manager_category_detail',
                                structure_slug=structure_slug,
                                category_slug=edited_category.slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    template = 'manager/category_edit.html'
    title = _('Modifica tipo di richiesta')
    sub_title = category
    d = {'category': category,
         'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_disable(request, structure_slug, category_slug, structure):
    """
    Disables a category

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    if category.is_active:
        category.is_active = False
        category.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Tipo di richieste {} disattivato con successo".format(category)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} disabled the category {}'.format(timezone.now(),
                                                          structure,
                                                          request.user,
                                                          category))

    else:
        messages.add_message(request, messages.ERROR,
                             _("Tipo di richieste {} già disattivato".format(category)))
    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_enable(request, structure_slug, category_slug, structure):
    """
    Enables a category

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    problem = category.something_stops_activation()
    if category.is_active:
        messages.add_message(request,
                             messages.ERROR,
                             _("Tipo di richieste {} già attivato".format(category)))
    elif problem:
        messages.add_message(request, messages.ERROR, problem)
    else:
        category.is_active = True
        category.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Tipo di richieste {} attivato con successo".format(category)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} enabled the category {}'.format(timezone.now(),
                                                         structure,
                                                         request.user,
                                                         category))

    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_delete(request, structure_slug, category_slug, structure):
    """
    Deletes a category

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    if category.can_be_deleted():

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} deleted the category {}'.format(timezone.now(),
                                                         structure,
                                                         request.user,
                                                         category))

        messages.add_message(request, messages.SUCCESS,
                             _("Categoria {} eliminata correttamente".format(category)))

        delete_directory(category.get_folder())

        category.delete()
        return redirect('uni_ticket:manager_dashboard',
                        structure_slug=structure_slug)
    messages.add_message(request, messages.ERROR,
                         _("Impossibile eliminare il tipo di richiesta {}."
                           " Ci sono ticket assegnati.".format(category)))
    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_input_module_new(request, structure_slug,
                              category_slug, structure):
    """
    Creates new input module for category

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    title = _('Nuovo modulo di inserimento')
    sub_title = _("Crea un nuovo modulo per il tipo di richiesta {}").format(category.name)
    form = CategoryInputModuleForm()
    if request.method == 'POST':
        form = CategoryInputModuleForm(request.POST)
        if form.is_valid():
            new_module = form.save(commit=False)
            new_module.ticket_category = category
            new_module.save()

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} created the module {}'
                        ' in the category {}'.format(timezone.now(),
                                                     structure,
                                                     request.user,
                                                     new_module,
                                                     category))

            messages.add_message(request, messages.SUCCESS,
                                 _("Modulo di inserimento <b>{}</b>"
                                   " creato con successo".format(new_module.name)))
            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=new_module.pk)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))

    template = 'manager/category_input_module_add_new.html'
    d = {'category': category,
         'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_module_edit(request, structure_slug,
                               category_slug, module_id, structure):
    """
    Edits input module details

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    form = CategoryInputModuleForm(instance=module)
    if request.method == 'POST':
        form = CategoryInputModuleForm(data=request.POST, instance=module)
        if form.is_valid():
            module_edited = form.save(commit=False)
            module_edited.save(update_fields = ['name'])

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} edited the module {}'
                        ' of the category {}'.format(timezone.now(),
                                                     structure,
                                                     request.user,
                                                     module,
                                                     category))

            messages.add_message(request, messages.SUCCESS,
                                 _("Modulo di inserimento modificato con successo"))
            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=module_id)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    title = _('Rinomina modulo [{}]').format(module)
    sub_title =  '{} - {}'.format(category, structure)
    template = 'manager/category_input_module_edit.html'
    d = {'category': category,
         'form': form,
         'module': module,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_module_enable(request, structure_slug,
                                 category_slug, module_id, structure):
    """
    Enables input module

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    if module.is_active:
        messages.add_message(request, messages.ERROR,
                             _("Modulo {} già attivato".format(module)))
    else:
        module.is_active = True
        module.save(update_fields = ['is_active'])
        module.disable_other_modules()
        messages.add_message(request, messages.SUCCESS,
                             _("Modulo {} attivato con successo".format(module)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} enabled the module {}'
                    ' of the category {}'.format(timezone.now(),
                                                 structure,
                                                 request.user,
                                                 module,
                                                 category))

    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_input_module_disable(request, structure_slug,
                                 category_slug, module_id, structure):
    """
    Disables input module

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    if not module.is_active:
        messages.add_message(request, messages.ERROR,
                             _("Modulo {} già disattivato".format(module)))
    else:
        category.is_active = False
        category.save(update_fields = ['is_active'])
        module.is_active = False
        module.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Modulo {} disattivato con successo".format(module)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} disabled the module {}'
                    ' and the category {}'.format(timezone.now(),
                                                  structure,
                                                  request.user,
                                                  module,
                                                  category))

    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_input_module_delete(request, structure_slug,
                                 category_slug, module_id, structure):
    """
    Deletes input module

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    if not module.can_be_deleted():

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} tried to delete'
                    ' the module {} of category {}'.format(timezone.now(),
                                                           structure,
                                                           request.user,
                                                           module,
                                                           category))

        messages.add_message(request, messages.ERROR,
                             _("Impossibile eliminare il modulo {}."
                               " Ci sono dei ticket collegati".format(module)))
    else:
        if module.is_active:
            category.is_active = False
            category.save(update_fields = ['is_active'])
            messages.add_message(request, messages.SUCCESS,
                                 _("Modulo <b>{}</b> eliminato con successo"
                                   " e tipo di richiesta <b>{}</b> disattivato"
                                   " (nessun modulo attivo)".format(module,
                                                                    category)))
        else: messages.add_message(request, messages.SUCCESS,
                                   _("Modulo {} eliminato con successo".format(module)))

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} deleted'
                    ' the module {} of category {}'.format(timezone.now(),
                                                           structure,
                                                           request.user,
                                                           module,
                                                           category))

        module.delete()
    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_input_module_details(request, structure_slug,
                                  category_slug, module_id, structure):
    """
    Shows category input module details

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule, pk=module_id)
    form = CategoryInputListForm()
    if request.method == 'POST':
        if not module.can_be_deleted():
            messages.add_message(request, messages.ERROR,
                                 _("Impossibile modificare il modulo"))
            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=module.pk)
        form = CategoryInputListForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            if TicketCategoryInputList.field_exist(module, name):
                messages.add_message(request, messages.ERROR,
                                     _("Esiste già un campo con questo"
                                       " nome: <b>{}</b>".format(name)))
            else:
                # is_required_value = form.cleaned_data['is_required']
                # is_required = False
                # if is_required_value == 'on': is_required=True
                input_list = form.save(commit=False)
                input_list.category_module = module
                input_list.save()
                messages.add_message(request, messages.SUCCESS,
                                     _("Campo di input creato con successo"))

                # log action
                logger.info('[{}] manager of structure {}'
                            ' {} inserted the field {}'
                            ' in the module {} of category {}'.format(timezone.now(),
                                                                   structure,
                                                                   request.user,
                                                                   name,
                                                                   module,
                                                                   category))

            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=module.pk)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    title = _('Gestione modulo [{}]').format(module)
    template = 'manager/category_input_module_detail.html'
    sub_title =  '{} - {}'.format(category, structure)
    d = {'category': category,
         'form': form,
         'module': module,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_field_delete(request, structure_slug,
                                category_slug, module_id,
                                field_id, structure):
    """
    Deletes a field from a category input module

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type field_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param field_id: module field id
    :param structure: structure object (from @is_manager)

    :return: redirect
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    if not module.can_be_deleted():

        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} tried to delete a field'
                    ' from module {} of category {}'.format(timezone.now(),
                                                            structure,
                                                            request.user,
                                                            module,
                                                            category))

        messages.add_message(request, messages.ERROR,
                             _("Impossibile eliminare il modulo {}."
                               " Ci sono dei ticket collegati".format(module)))
    else:
        field = get_object_or_404(TicketCategoryInputList,
                                  pk=field_id,
                                  category_module=module)
        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} deleted the field {}'
                    ' from module {} of category {}'.format(timezone.now(),
                                                            structure,
                                                            request.user,
                                                            field,
                                                            module,
                                                            category))
        field.delete()
        messages.add_message(request, messages.SUCCESS,
                             _("Campo {} eliminato con successo".format(field.name)))
    return redirect('uni_ticket:manager_category_input_module',
                    structure_slug=structure_slug,
                    category_slug=category_slug,
                    module_id=module_id)

@login_required
@is_manager
def category_input_module_preview(request, structure_slug,
                                  category_slug, module_id, structure):
    """
    Shows input module form preview

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    form = module.get_form(show_conditions=True)
    title = _('Anteprima modulo di inserimento')
    sub_title = "{} in {}".format(module, category)
    template = 'manager/category_input_module_preview.html'
    clausole_categoria = category.get_conditions()
    d = {'category': category,
         'conditions': clausole_categoria,
         'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_field_edit(request, structure_slug,
                              category_slug, module_id,
                              field_id, structure):
    """
    Edits field details from a category input module

    :type structure_slug: String
    :type category_slug: String
    :type module_id: Integer
    :type field_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param module_id: input module id
    :param field_id: module field id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    field = get_object_or_404(TicketCategoryInputList,
                              pk=field_id,
                              category_module=module)
    form = CategoryInputListForm(instance=field)
    if request.method ==  'POST':
        if not module.can_be_deleted():

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} tried to edit a field'
                        ' from module {} of category {}'.format(timezone.now(),
                                                                structure,
                                                                request.user,
                                                                module,
                                                                category))

            messages.add_message(request, messages.ERROR,
                                 _("Impossibile modificare il campo"))
            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=module_id)
        form = CategoryInputListForm(data=request.POST, instance=field)
        if form.is_valid():
            form.save()

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} edited the field {}'
                        ' from module {} of category {}'.format(timezone.now(),
                                                                structure,
                                                                request.user,
                                                                field,
                                                                module,
                                                                category))

            messages.add_message(request, messages.SUCCESS,
                                 _("Campo di input modificato con successo"))
            return redirect('uni_ticket:manager_category_input_module',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            module_id=module.pk)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))

    title = _('Modifica campo di input [{}]').format(field.name)
    sub_title = "{} - {} - {}".format(module, module.ticket_category, structure)
    template = 'manager/category_input_field_edit.html'
    d = {'category': category,
         'field': field,
         'form': form,
         'module': module,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_condition_new(request, structure_slug,
                           category_slug, structure):
    """
    Creates a new condition for category

    :type structure_slug: String
    :type category_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Nuova clausola per inserimento ticket')
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    form = CategoryConditionForm()
    if request.method == 'POST':
        form = CategoryConditionForm(request.POST, request.FILES)
        if form.is_valid():
            condition = form.save(commit=False)
            condition.text = escape(form.cleaned_data['text'])
            condition.category = category
            condition.save()

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} created the new condition {}'
                        ' for category {}'.format(timezone.now(),
                                                  structure,
                                                  request.user,
                                                  condition,
                                                  category))

            messages.add_message(request, messages.SUCCESS,
                                 _("Clausola creata con successo"))
            return redirect('uni_ticket:manager_category_detail',
                            structure_slug=structure_slug,
                            category_slug=category_slug)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))

    template = 'manager/category_condition_add_new.html'
    d = {'category': category,
         'form': form,
         'structure': structure,
         'sub_title': category,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_condition_edit(request, structure_slug, category_slug,
                            condition_id, structure):
    """
    Edits condition details

    :type structure_slug: String
    :type category_slug: String
    :type condition_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param condition_id: condition id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    condition = get_object_or_404(TicketCategoryCondition,
                                  pk=condition_id,
                                  category=category)
    form = CategoryConditionForm(instance=condition)
    if request.method == 'POST':
        form = CategoryConditionForm(instance=condition,
                                     data=request.POST,
                                     files=request.FILES)
        if form.is_valid():
            edited_category = form.save(commit=False)
            edited_category.text = escape(form.cleaned_data['text'])
            edited_category.save()

            # log action
            logger.info('[{}] manager of structure {}'
                        ' {} edited a condition'
                        ' for category {}'.format(timezone.now(),
                                                  structure,
                                                  request.user,
                                                  category))

            messages.add_message(request, messages.SUCCESS,
                                 _("Clausola modificata con successo"))
            return redirect('uni_ticket:manager_category_condition_detail',
                            structure_slug=structure_slug,
                            category_slug=category_slug,
                            condition_id=condition_id)
        else:
            for k,v in get_labeled_errors(form).items():
                messages.add_message(request, messages.ERROR,
                                     "<b>{}</b>: {}".format(k, strip_tags(v)))
    template = 'manager/category_condition_edit.html'
    title = _('Modifica clausola')
    sub_title = condition
    d = {'condition': condition,
         'form': form,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_condition_delete(request, structure_slug, category_slug,
                              condition_id, structure):
    """
    Deletes condition from a category

    :type structure_slug: String
    :type category_slug: String
    :type condition_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param condition_id: condition id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    condition = get_object_or_404(TicketCategoryCondition,
                                  pk=condition_id,
                                  category=category)
    messages.add_message(request, messages.SUCCESS,
                         _("Clausola {} eliminata correttamente".format(condition)))

    # log action
    logger.info('[{}] manager of structure {}'
                ' {} deleted a condition'
                ' for category {}'.format(timezone.now(),
                                          structure,
                                          request.user,
                                          category))

    # delete condition attachment
    delete_file(file_name=condition.attachment)

    condition.delete()
    return redirect('uni_ticket:manager_category_detail',
                            structure_slug=structure_slug,
                            category_slug=category_slug)

@login_required
@is_manager
def category_condition_disable(request, structure_slug, category_slug,
                               condition_id, structure):
    """
    Disables a condition from a category

    :type structure_slug: String
    :type category_slug: String
    :type condition_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param condition_id: condition id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    condition = get_object_or_404(TicketCategoryCondition,
                                  pk=condition_id,
                                  category=category)
    if condition.is_active:
        condition.is_active = False
        condition.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Clausola {} disattivata con successo".format(condition)))
        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} disabled a condition'
                    ' for category {}'.format(timezone.now(),
                                              structure,
                                              request.user,
                                              category))
    else:
        messages.add_message(request, messages.ERROR,
                             _("Clausola {} già disattivata".format(condition)))
    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_condition_enable(request, structure_slug, category_slug,
                               condition_id, structure):
    """
    Enables a condition from a category

    :type structure_slug: String
    :type category_slug: String
    :type condition_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param condition_id: condition id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    condition = get_object_or_404(TicketCategoryCondition,
                                  pk=condition_id,
                                  category=category)
    if condition.is_active:
        messages.add_message(request, messages.ERROR,
                             _("Clausola {} già attivata".format(condition)))
    else:
        condition.is_active = True
        condition.save(update_fields = ['is_active'])
        messages.add_message(request, messages.SUCCESS,
                             _("Clausola {} attivata con successo".format(condition)))
        # log action
        logger.info('[{}] manager of structure {}'
                    ' {} enabled a condition'
                    ' for category {}'.format(timezone.now(),
                                              structure,
                                              request.user,
                                              category))

    return redirect('uni_ticket:manager_category_detail',
                    structure_slug=structure_slug,
                    category_slug=category_slug)

@login_required
@is_manager
def category_condition_detail(request, structure_slug, category_slug,
                              condition_id, structure):
    """
    Shows condition details

    :type structure_slug: String
    :type category_slug: String
    :type condition_id: Integer
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param category_slug: category slug
    :param condition_id: condition id
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Gestione dettaglio clausola')
    template = 'manager/category_condition_detail.html'
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    condition = get_object_or_404(TicketCategoryCondition,
                                  pk=condition_id,
                                  category=category)
    d = {'category': category,
         'condition': condition,
         'structure': structure,
         'sub_title': condition,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def categories(request, structure_slug, structure):
    """
    Retrieves structure categories list

    :type structure_slug: String
    :type structure: OrganizationalStructure (from @is_manager)

    :param structure_slug: structure slug
    :param structure: structure object (from @is_manager)

    :return: render
    """
    title = _('Gestione tipi di richiesta')
    template = 'manager/categories.html'
    # sub_title = _("gestione ufficio livello manager")
    categories = TicketCategory.objects.filter(organizational_structure=structure)

    d = {'categories': categories,
         'structure': structure,
         # 'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_module_clone_preload(request, structure_slug,
                                        category_slug, module_id,
                                        selected_structure_slug=None,
                                        selected_category_slug=None,
                                        structure=None):
    """
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    structures = OrganizationalStructure.objects.filter(is_active=True)
    my_structures = []
    categories = []
    for struct in structures:
        if user_is_manager(request.user, struct):
            my_structures.append(struct)
    title = _('Clona modulo [{}] ({} - {})').format(module, category, structure)
    template = 'manager/category_input_module_clone.html'
    sub_title = _("Seleziona la struttura")
    if selected_structure_slug:
        selected_structure = get_object_or_404(OrganizationalStructure,
                                               slug=selected_structure_slug,
                                               is_active=True)

        # another check if user is a manager of selected structure
        if not user_is_manager(request.user, selected_structure):
            return custom_message(request, _("Non sei un manager della struttura selezionata"),
                                  structure_slug=structure.slug)

        categories = TicketCategory.objects.filter(organizational_structure=selected_structure)
        sub_title = _("Seleziona la Categoria")
    if selected_category_slug:
        selected_category = get_object_or_404(TicketCategory,
                                              organizational_structure=selected_structure,
                                              slug=selected_category_slug)

    d = {'categories': categories,
         'category': category,
         'module': module,
         'my_structures': my_structures,
         'selected_category_slug': selected_category_slug,
         'selected_structure_slug': selected_structure_slug,
         'structure': structure,
         'sub_title': sub_title,
         'title': title,}
    return render(request, template, d)

@login_required
@is_manager
def category_input_module_clone(request, structure_slug,
                                category_slug, module_id,
                                selected_structure_slug,
                                selected_category_slug,
                                structure):
    """
    """
    category = get_object_or_404(TicketCategory,
                                 organizational_structure=structure,
                                 slug=category_slug)
    module = get_object_or_404(TicketCategoryModule,
                               pk=module_id,
                               ticket_category=category)
    selected_structure = get_object_or_404(OrganizationalStructure,
                                               slug=selected_structure_slug,
                                               is_active=True)

    # check if user is manager of selected structure
    if not user_is_manager(request.user, selected_structure):
            return custom_message(request, _("Non sei un manager della struttura selezionata"),
                                  structure_slug=structure.slug)

    selected_category = get_object_or_404(TicketCategory,
                                          organizational_structure=selected_structure,
                                          slug=selected_category_slug)
    # create new module in selected category with master module name
    new_module = TicketCategoryModule.objects.create(name=module.name,
                                                     ticket_category=selected_category)

    # get all input fields of master module and clone these in new module
    master_module_inputlist = TicketCategoryInputList.objects.filter(category_module=module)
    for module_input in master_module_inputlist:
        input_dict = module_input.__dict__
        del input_dict['_state']
        del input_dict['id']
        input_dict['category_module_id'] = new_module.pk
        TicketCategoryInputList.objects.create(**input_dict)

    # log action
    logger.info('[{}] manager of structure {}'
                ' {} cloned the module {} of category {}'
                ' in the category {} ({})'.format(timezone.now(),
                                             structure,
                                             request.user,
                                             module,
                                             category,
                                             selected_category,
                                             selected_structure))

    messages.add_message(request, messages.SUCCESS,
                         _("Modulo di input <b>{}</b> clonato con successo"
                         " nel tipo di richieste <b>{}</b>".format(module.name,
                                                                   selected_category)))
    return redirect('uni_ticket:manager_category_input_module',
                    structure_slug=selected_structure.slug,
                    category_slug=selected_category.slug,
                    module_id=new_module.pk)
