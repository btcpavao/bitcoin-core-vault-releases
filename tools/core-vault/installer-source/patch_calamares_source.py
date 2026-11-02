#!/usr/bin/env python3
"""Apply version-bounded Bitcoin Core Vault installer safety and UX changes."""
from pathlib import Path
import argparse, re, shutil

MARK='CORE_OFFLINE_INTEGRATION'

def once(text, old, new, name):
    if text.count(old) != 1:
        raise RuntimeError(f"{name}: expected exactly one upstream anchor; found {text.count(old)}")
    return text.replace(old, new, 1)

def mask_cpp_noncode(text):
    out=list(text); i=0; n=len(text)
    def blank(a,b):
        for p in range(a,b):
            if text[p] not in '\r\n': out[p]=' '
    while i<n:
        start=i
        if text.startswith('//',i):
            end=text.find('\n',i+2); end=n if end<0 else end; blank(i,end); i=end
        elif text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0: raise RuntimeError('Unterminated block comment')
            end+=2; blank(i,end); i=end
        elif text.startswith('R"',i):
            opening=text.find('(',i+2,min(i+19,n))
            if opening<0: raise RuntimeError('Unsupported raw string')
            delim=text[i+2:opening]; closing=')'+delim+'"'; end=text.find(closing,opening+1)
            if end<0: raise RuntimeError('Unterminated raw string')
            end+=len(closing); blank(i,end); i=end
        elif text[i] in ('"',"'"):
            q=text[i]
            if q=="'" and i>0 and i+1<n and text[i-1].isalnum() and text[i+1].isalnum():
                tok=re.search(r"[A-Za-z0-9_']+$",text[:i])
                if tok and tok.group()[0].isdigit(): i+=1; continue
            i+=1
            while i<n:
                if text[i]=='\\': i+=2
                elif text[i]==q: i+=1; break
                elif text[i]=='\n': raise RuntimeError('Unterminated literal')
                else: i+=1
            else: raise RuntimeError('Unterminated literal')
            blank(start,i)
        else: i+=1
    return ''.join(out)

def function_bounds(text, signature):
    masked=mask_cpp_noncode(text)
    pat=r'(?m)^[ \t]*'+re.escape(signature)+r'[ \t\r\n]*\{'
    matches=list(re.finditer(pat,masked))
    if len(matches)!=1:
        raise RuntimeError(f'Expected one definition of {signature}; found {len(matches)}')
    opening=masked.rfind('{',matches[0].start(),matches[0].end())
    depth=0
    for pos in range(opening,len(masked)):
        if masked[pos]=='{': depth+=1
        elif masked[pos]=='}':
            depth-=1
            if depth==0: return matches[0].start(), pos+1, opening
    raise RuntimeError(f'Unbalanced function {signature}')

def append_function(text, signature, addition):
    start,end,opening=function_bounds(text,signature)
    return text[:end-1]+addition+'\n'+text[end-1:]

def replace_function(text, signature, new_body):
    start,end,opening=function_bounds(text,signature)
    prefix=text[start:opening+1]
    return text[:start]+prefix+'\n'+new_body.rstrip()+'\n}'+text[end:]

def patch(src, header, *, check_only=False):
    changelog=(src/'debian/changelog').read_text()
    if not re.match(r'calamares \(3\.3\.14-[^)]*\)',changelog):
        raise RuntimeError('Patch is limited to Debian Calamares 3.3.14')
    rels=[
      'partition/gui/ChoicePage.cpp','partition/core/PartitionCoreModule.cpp',
      'partition/PartitionViewStep.cpp','keyboard/KeyboardPage.cpp','keyboard/Config.cpp',
      'summary/Config.cpp','finished/FinishedPage.cpp']
    paths={r:src/'src/modules'/r for r in rels}
    paths['ui/CalamaresWindow.cpp']=src/'src/calamares/CalamaresWindow.cpp'
    texts={k:p.read_text() for k,p in paths.items()}
    if any(MARK in t for t in texts.values()):
        raise RuntimeError('Source already patched; use a clean Debian source extraction')

    # Disk UI + safety restrictions.
    c=texts['partition/gui/ChoicePage.cpp']
    c=append_function(c,'ChoicePage::setupActions()',r'''
    // CORE_OFFLINE_INTEGRATION: whole-disk erase is the only supported install operation.
    force_uncheck(m_grp, m_replaceButton);
    force_uncheck(m_grp, m_alongsideButton);
    force_uncheck(m_grp, m_somethingElseButton);
''')
    c=once(c,'    return panelWidget;',
           '    panelWidget->hide(); // CORE_OFFLINE_INTEGRATION\n    return panelWidget;','bootloader panel')
    c=once(c,'    updateDeviceStatePreview();\n\n    // Preview setup done.',
           '    m_core->setBootLoaderInstallPath(currd->deviceNode()); // CORE_OFFLINE_INTEGRATION\n'
           '    updateDeviceStatePreview();\n\n    // Preview setup done.','automatic bootloader disk')
    c=once(c,'    setupUi( this );',r'''    setupUi( this );

    // CORE_OFFLINE_INTEGRATION: clear appliance-style disk page copy.
    auto* pageTitle = new QLabel(QStringLiteral("Choose where to install Bitcoin Core Vault"), this);
    pageTitle->setObjectName(QStringLiteral("coreOfflinePageTitle"));
    auto* pageDescription = new QLabel(
        QStringLiteral("Select one internal drive. The selected drive will be completely erased and dedicated to Bitcoin Core Vault."), this);
    pageDescription->setObjectName(QStringLiteral("coreOfflinePageDescription"));
    pageDescription->setWordWrap(true);
    m_mainLayout->setContentsMargins(110, 0, 110, 0);
    m_mainLayout->setSpacing(12);
    m_mainLayout->insertWidget(0, pageDescription);
    m_mainLayout->insertWidget(0, pageTitle);''','disk page heading')
    c=once(c,'    BootInfoWidget* bootInfoWidget = new BootInfoWidget( this );',
           '    BootInfoWidget* bootInfoWidget = new BootInfoWidget( this );\n    bootInfoWidget->hide(); // CORE_OFFLINE_INTEGRATION','hide boot mode')
    c=once(c,'    m_deviceInfoWidget = new DeviceInfoWidget;',
           '    m_deviceInfoWidget = new DeviceInfoWidget;\n    m_deviceInfoWidget->hide(); // CORE_OFFLINE_INTEGRATION','hide partition table badge')
    c=once(c,'    m_messageLabel->setWordWrap( true );\n    m_messageLabel->hide();',r'''    m_messageLabel->setWordWrap( true );
    m_messageLabel->hide();

    auto* eraseWarning = new QLabel(
        QStringLiteral("Everything currently stored on the selected drive will be permanently erased."), this);
    eraseWarning->setObjectName(QStringLiteral("coreOfflineEraseWarning"));
    eraseWarning->setWordWrap(true);
    m_mainLayout->insertWidget(3, eraseWarning);

    // Hide Calamares' generic operation chooser and technical before/after partition diagrams.
    m_itemsScrollArea->hide();
    hLine->hide();
    m_previewBeforeLabel->hide();
    m_previewBeforeFrame->hide();
    m_previewAfterLabel->hide();
    m_previewAfterFrame->hide();
    m_selectLabel->hide();''','disk simplified UI')
    c=once(c,'    m_drivesLabel->setText( tr( "Select storage de&vice:", "@label" ) );',
           '    m_drivesLabel->setText( tr( "Installation drive:", "@label" ) );','drive label')
    c=once(c,'        m_config->setInstallChoice( m_config->initialInstallChoice() );\n        checkInstallChoiceRadioButton( m_config->installChoice() );',
           '        m_config->setInstallChoice( InstallChoice::Erase ); // CORE_OFFLINE_INTEGRATION\n        checkInstallChoiceRadioButton( InstallChoice::Erase );','auto erase choice')
    texts['partition/gui/ChoicePage.cpp']=c

    # Disk target filtering and pre-write revalidation.
    c=texts['partition/core/PartitionCoreModule.cpp']
    c=once(c,'#include "core/PartitionCoreModule.h"',
           '#include "core/PartitionCoreModule.h"\n#include "CoreOfflineGuard.h"','guard include')
    c=once(c,'    DeviceList devices = PartUtils::getDevices( PartUtils::DeviceType::WritableOnly );',r'''    // CORE_OFFLINE_INTEGRATION: omit unsafe targets from the drive selector.
    DeviceList detected = PartUtils::getDevices( PartUtils::DeviceType::WritableOnly );
    DeviceList devices;
    coreOfflineDiskIdentity.clear();
    for (auto* d : detected) {
        if (!d) continue;
        const auto identity = coreOfflineProbe(d->deviceNode());
        if (!identity.isEmpty()) {
            devices.append(d);
            coreOfflineDiskIdentity[d->deviceNode()] = identity;
        } else {
            delete d;
        }
    }''','device filtering')
    c=once(c,'    Calamares::JobList lst;\n    QList< Device* > devices;',r'''    Calamares::JobList lst;
    QList< Device* > devices;
    // CORE_OFFLINE_INTEGRATION: validate selected disk immediately before writes.
    QStringList dirty;
    for (const auto* info : m_deviceInfos) {
        if (info->isDirty()) dirty.append(info->device->deviceNode());
    }
    lst << Calamares::job_ptr(new CoreOfflineDiskGuard(
        dirty, config->installChoice() == Config::InstallChoice::Erase));''','pre-write disk guard')
    c=once(c,'    m_osproberLines = PartUtils::runOsprober( this->deviceModel() );',
           '    m_osproberLines.clear(); // CORE_OFFLINE_INTEGRATION: whole-disk appliance install only.','disable OS probing')
    texts['partition/core/PartitionCoreModule.cpp']=c

    # Keyboard page: explanatory text and only layout/variant controls.
    c=texts['keyboard/KeyboardPage.cpp']
    c=once(c,'#include <QComboBox>','#include <QComboBox>\n#include <QLabel>','keyboard label include')
    c=once(c,'    ui->setupUi( this );',r'''    ui->setupUi( this );
    // CORE_OFFLINE_INTEGRATION: only layout + variant are user choices.
    ui->label->hide();
    ui->physicalModelSelector->hide();
    ui->buttonRestore->hide();
    ui->label_2->hide();
    ui->groupSelector->hide();

    auto* pageTitle = new QLabel(QStringLiteral("Choose your keyboard layout"), this);
    pageTitle->setObjectName(QStringLiteral("coreOfflinePageTitle"));
    auto* pageDescription = new QLabel(
        QStringLiteral("Bitcoin Core Vault and the installer stay in English. Choose only how your physical keyboard should behave."), this);
    pageDescription->setObjectName(QStringLiteral("coreOfflinePageDescription"));
    pageDescription->setWordWrap(true);
    pageTitle->setAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    pageDescription->setAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    pageTitle->setMargin(0);
    pageDescription->setMargin(0);
    ui->verticalLayout->setContentsMargins(90, 0, 90, 0);
    ui->verticalLayout->setSpacing(10);
    ui->verticalLayout->insertWidget(0, pageDescription);
    ui->verticalLayout->insertWidget(0, pageTitle);

    auto* headings = new QHBoxLayout;
    auto* layoutHeading = new QLabel(QStringLiteral("Keyboard layout"), this);
    auto* variantHeading = new QLabel(QStringLiteral("Variant"), this);
    layoutHeading->setObjectName(QStringLiteral("coreOfflineFieldLabel"));
    variantHeading->setObjectName(QStringLiteral("coreOfflineFieldLabel"));
    headings->addWidget(layoutHeading, 1);
    headings->addWidget(variantHeading, 1);
    ui->verticalLayout->insertLayout(2, headings);
    ui->LE_TestKeyboard->setPlaceholderText(QStringLiteral("Type here to test your keyboard"));''','keyboard page heading')
    c=once(c,'    ui->KBPreviewLayout->addWidget( m_keyboardPreview );',
           '    ui->KBPreviewLayout->addWidget( m_keyboardPreview );\n    m_keyboardPreview->hide(); // CORE_OFFLINE_INTEGRATION','hide keyboard preview')
    texts['keyboard/KeyboardPage.cpp']=c

    # Cleaner keyboard summary.
    c=texts['keyboard/Config.cpp']
    c=replace_function(c,'Config::prettyStatus() const',r'''    QString layout = m_keyboardLayoutsModel->item( m_keyboardLayoutsModel->currentIndex() ).second.description;
    QString variant = m_keyboardVariantsModel->currentIndex() >= 0
        ? m_keyboardVariantsModel->label( m_keyboardVariantsModel->currentIndex() )
        : QStringLiteral("Default");
    return tr( "<b>Keyboard layout</b><br/>%1 · %2", "@label" ).arg( layout, variant );''')
    texts['keyboard/Config.cpp']=c

    # Plain-language disk review instead of raw partition jobs / MSDOS jargon.
    c=texts['partition/PartitionViewStep.cpp']
    c=replace_function(c,'PartitionViewStep::prettyStatus() const',r'''    const QList< PartitionCoreModule::SummaryInfo > list = m_core->createSummaryInfo();
    if ( list.isEmpty() )
    {
        return tr( "No installation drive selected." );
    }
    const auto& info = list.first();
    return tr( "<b>Installation drive</b><br/>%1 <span style='color:#aaaaaa'>(%2)</span><br/><br/>"
               "The selected drive will be completely erased and dedicated to Bitcoin Core Vault." )
        .arg( info.deviceName, info.deviceNode );''')
    c=replace_function(c,'PartitionViewStep::createSummaryWidget() const',r'''    QWidget* widget = new QWidget;
    QVBoxLayout* layout = new QVBoxLayout( widget );
    layout->setContentsMargins( 70, 10, 70, 10 );
    layout->setSpacing( 14 );

    const QList< PartitionCoreModule::SummaryInfo > list = m_core->createSummaryInfo();
    if ( list.isEmpty() )
    {
        auto* missing = new QLabel( tr( "No installation drive selected." ), widget );
        missing->setObjectName( "coreOfflineEraseWarning" );
        layout->addWidget( missing );
        return widget;
    }

    const auto& info = list.first();
    auto* drive = new QLabel(
        tr( "<b>Installation drive</b><br/>%1<br/><span style='color:#aaaaaa'>%2</span>" )
            .arg( info.deviceName, info.deviceNode ), widget );
    drive->setObjectName( "coreOfflineReviewCard" );
    drive->setWordWrap( true );
    layout->addWidget( drive );

    auto* action = new QLabel(
        tr( "<b>What will happen</b><br/>The selected drive will be erased. Bitcoin Core Vault will be installed as a dedicated offline environment. No username, password, network, or timezone setup is required." ), widget );
    action->setObjectName( "coreOfflineReviewCard" );
    action->setWordWrap( true );
    layout->addWidget( action );

    auto* warning = new QLabel(
        tr( "Everything currently stored on this drive will be permanently erased." ), widget );
    warning->setObjectName( "coreOfflineEraseWarning" );
    warning->setWordWrap( true );
    layout->addWidget( warning );

    auto* technical = new QLabel(
        tr( "Technical details: whole-disk installation · ext4 filesystem · swap disabled · GRUB bootloader · target %1" ).arg( info.deviceNode ), widget );
    technical->setObjectName( "coreOfflineTechnicalDetails" );
    technical->setWordWrap( true );
    layout->addWidget( technical );
    layout->addStretch();
    return widget;''')
    texts['partition/PartitionViewStep.cpp']=c

    # Review copy.
    c=texts['summary/Config.cpp']
    c=replace_function(c,'Config::retranslate()',r'''    m_title = tr( "Review", "@label" );
    m_message = tr( "Review your choices before installation. Nothing is written to disk until you press Install Bitcoin Core Vault." );
    Q_EMIT titleChanged( m_title );
    Q_EMIT messageChanged( m_message );''')
    texts['summary/Config.cpp']=c

    # Finished page: no Calamares restart checkbox; one clear action in nav.
    c=texts['finished/FinishedPage.cpp']
    c=once(c,'    ui->setupUi( this );',
           '    ui->setupUi( this );\n    ui->restartCheckBox->hide(); // CORE_OFFLINE_INTEGRATION','hide restart checkbox')
    c=once(c,'             [ this ]( Config::RestartMode mode )\n             {\n                 using Mode = Config::RestartMode;\n\n                 ui->restartCheckBox->setVisible( mode != Mode::Never );\n                 ui->restartCheckBox->setEnabled( mode != Mode::Always );\n             } );','             [ this ]( Config::RestartMode )\n             {\n                 ui->restartCheckBox->hide();\n                 ui->restartCheckBox->setEnabled( false );\n             } );','keep restart checkbox hidden')
    c=replace_function(c,'FinishedPage::retranslate()',r'''    ui->retranslateUi( this );
    if ( !m_failure.has_value() )
    {
        ui->mainText->setText(
            QStringLiteral(
                "<h1>Bitcoin Core Vault is ready.</h1><br/>"
                "The installation completed successfully.<br/>"
                "Restart this computer to boot directly into Bitcoin Core.<br/><br/>"
                "<span style='color:#aaaaaa'>The installed Vault keeps its normal workspace on disk. Private Workspace remains in volatile memory and starts empty after every reboot.</span>" ) );
    }
    else
    {
        ui->mainText->setText(
            tr( "<h1>Installation failed.</h1><br/>Bitcoin Core Vault was not installed.<br/><br/>%1", "@info" )
                .arg( m_failure.value() ) );
    }''')
    texts['finished/FinishedPage.cpp']=c

    # Global header with 3-step indicator and installer-specific navigation labels.
    c=texts['ui/CalamaresWindow.cpp']
    original_body=c[c.index('    const Calamares::Branding* const branding =',c.index('getWidgetSidebar(')):c.index('static QWidget*\ngetWidgetNavigation(')]
    if not original_body.rstrip().endswith('}'):
        raise RuntimeError('Unexpected sidebar source shape')
    replacement_body=r'''    // CORE_OFFLINE_INTEGRATION: Bitcoin Core Vault product header + three-step installer progress.
    auto* box = new QWidget(parent);
    auto* layout = new QVBoxLayout(box);
    layout->setContentsMargins(16, 6, 16, 6);
    layout->setSpacing(4);

    auto* logo = new QLabel(box);
    logo->setAlignment(Qt::AlignCenter);
    logo->setPixmap(QPixmap("/etc/calamares/branding/core-offline/bitcoin.png").scaled(
        44, 44, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    layout->addWidget(logo);

    auto* title = new QLabel(QStringLiteral("Bitcoin Core Vault"), box);
    title->setAlignment(Qt::AlignCenter);
    title->setObjectName(QStringLiteral("coreOfflineProductTitle"));
    layout->addWidget(title);

    auto* subtitle = new QLabel(QStringLiteral("Installer"), box);
    subtitle->setAlignment(Qt::AlignCenter);
    subtitle->setObjectName(QStringLiteral("coreOfflineProductSubtitle"));
    layout->addWidget(subtitle);

    auto* steps = new QHBoxLayout;
    steps->setContentsMargins(0, 4, 0, 0);
    steps->setSpacing(8);
    auto* step1 = new QLabel(box);
    auto* step2 = new QLabel(box);
    auto* step3 = new QLabel(box);
    auto* sep1 = new QLabel(QStringLiteral("────────"), box);
    auto* sep2 = new QLabel(QStringLiteral("────────"), box);
    for (auto* s : { step1, step2, step3 }) {
        s->setAlignment(Qt::AlignCenter);
        s->setFixedWidth(124);
    }
    for (auto* sep : { sep1, sep2 }) {
        sep->setAlignment(Qt::AlignCenter);
        sep->setFixedWidth(64);
    }
    sep1->setObjectName(QStringLiteral("coreOfflineStepSeparator"));
    sep2->setObjectName(QStringLiteral("coreOfflineStepSeparator"));
    steps->addStretch(); steps->addWidget(step1); steps->addWidget(sep1);
    steps->addWidget(step2); steps->addWidget(sep2); steps->addWidget(step3); steps->addStretch();
    layout->addLayout(steps);

    auto* vm = Calamares::ViewManager::instance();
    auto updateSteps = [vm, step1, step2, step3]() {
        const int current = vm->currentStepIndex();
        auto style = [current](QLabel* label, int index, const QString& name) {
            if (current > index) {
                label->setText(QStringLiteral("✓  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { color:#ffffff; padding:6px 10px; font-weight:600; }"));
            } else if (current == index) {
                label->setText(QString::number(index + 1) + QStringLiteral("  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { background:#ffffff; color:#000000; border-radius:13px; padding:6px 12px; font-weight:700; }"));
            } else {
                label->setText(QString::number(index + 1) + QStringLiteral("  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { color:#777777; padding:6px 10px; }"));
            }
        };
        if (current >= 3) {
            step1->setText(QStringLiteral("✓  Keyboard"));
            step2->setText(QStringLiteral("✓  Disk"));
            step3->setText(QStringLiteral("✓  Review"));
            for (auto* s : { step1, step2, step3 }) {
                s->setStyleSheet(QStringLiteral("QLabel { color:#ffffff; padding:6px 10px; font-weight:600; }"));
            }
        } else {
            style(step1, 0, QStringLiteral("Keyboard"));
            style(step2, 1, QStringLiteral("Disk"));
            style(step3, 2, QStringLiteral("Review"));
        }
    };
    QObject::connect(vm, &Calamares::ViewManager::currentStepChanged, box, updateSteps);
    updateSteps();
    box->setFixedHeight(154);
    return box;
}

'''
    c=once(c,original_body,replacement_body,'branded header and stepper')
    c=once(c,'    navigation->setLayout( bottomLayout );',r'''    // CORE_OFFLINE_INTEGRATION: keep upstream controls, add branded footer and plain-language button labels.
    auto* frame = new QVBoxLayout;
    frame->setContentsMargins(8, 0, 8, 4);
    frame->addLayout(bottomLayout);

    auto* footerLogo = new QLabel(navigation);
    footerLogo->setAlignment(Qt::AlignCenter);
    footerLogo->setPixmap(QPixmap("/etc/calamares/branding/core-offline/debian.png").scaled(
        28, 28, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    frame->addWidget(footerLogo);
    auto* credit = new QLabel(QStringLiteral("Powered by Debian GNU/Linux"), navigation);
    credit->setAlignment(Qt::AlignCenter);
    credit->setObjectName(QStringLiteral("coreOfflineDebianCredit"));
    frame->addWidget(credit);
    navigation->setLayout(frame);

    auto updateNavigation = [viewManager, navigation]() {
        auto* back = navigation->findChild<QPushButton*>(QStringLiteral("view-button-back"));
        auto* next = navigation->findChild<QPushButton*>(QStringLiteral("view-button-next"));
        auto* quit = navigation->findChild<QPushButton*>(QStringLiteral("view-button-cancel"));
        if (!back || !next || !quit) return;
        for (auto* button : { back, next, quit }) {
            button->setMinimumWidth(140);
            button->setMinimumHeight(40);
        }
        quit->setStyleSheet(QString());
        const int i = viewManager->currentStepIndex();
        if (i == 0) {
            back->hide(); next->show(); next->setText(QStringLiteral("Continue")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i == 1) {
            back->show(); next->show(); next->setText(QStringLiteral("Continue")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i == 2) {
            back->show(); next->show(); next->setText(QStringLiteral("Erase drive & install")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i >= 4) {
            back->hide();
            next->hide();
            quit->show();
            quit->setText(QStringLiteral("Restart into Bitcoin Core"));
            quit->setMinimumWidth(220);
            quit->setStyleSheet(QStringLiteral(
                "QPushButton { background:#ffffff; color:#000000; border:1px solid #ffffff; "
                "border-radius:6px; padding:9px 18px; font-weight:600; } "
                "QPushButton:hover { background:#e7e7e7; border-color:#e7e7e7; } "
                "QPushButton:focus { border:2px solid #f7931a; }"));
        }
    };
    QObject::connect(viewManager, &Calamares::ViewManager::currentStepChanged, navigation, updateNavigation);
    QObject::connect(viewManager, &Calamares::ViewManager::nextLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    QObject::connect(viewManager, &Calamares::ViewManager::quitLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    QObject::connect(viewManager, &Calamares::ViewManager::backLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    updateNavigation();''','branded footer/navigation')
    texts['ui/CalamaresWindow.cpp']=c


    # CORE_OFFLINE_POLISH_V2: patch the actual execution/progress view.
    execution_path=src/'src/libcalamaresui/viewpages/ExecutionViewStep.cpp'
    execution=execution_path.read_text()
    execution=once(execution,'#include <QPlainTextEdit>\n#include <QProgressBar>','#include <QPlainTextEdit>\n#include <QPixmap>\n#include <QProgressBar>','execution QPixmap include')
    execution=once(execution,'    m_tab_widget->addTab( m_slideshow->widget(), "Slideshow" );','    auto* progressPanel = new QWidget( m_tab_widget );\n    progressPanel->setObjectName( QStringLiteral("coreOfflineExecutionPanel") );\n\n    auto* progressLayout = new QVBoxLayout( progressPanel );\n    progressLayout->setContentsMargins( 120, 36, 120, 36 );\n    progressLayout->setSpacing( 14 );\n    progressLayout->addStretch();\n\n    auto* progressLogo = new QLabel( progressPanel );\n    progressLogo->setAlignment( Qt::AlignCenter );\n    progressLogo->setPixmap(\n        QPixmap("/etc/calamares/branding/core-offline/bitcoin.png")\n            .scaled( 68, 68, Qt::KeepAspectRatio, Qt::SmoothTransformation ) );\n    progressLayout->addWidget( progressLogo );\n\n    auto* progressTitle = new QLabel(\n        QStringLiteral("Installing Bitcoin Core Vault"), progressPanel );\n    progressTitle->setObjectName( QStringLiteral("coreOfflineExecutionTitle") );\n    progressTitle->setAlignment( Qt::AlignCenter );\n    progressLayout->addWidget( progressTitle );\n\n    auto* progressDescription = new QLabel(\n        QStringLiteral("Preparing the selected drive and copying the offline environment."),\n        progressPanel );\n    progressDescription->setObjectName( QStringLiteral("coreOfflineExecutionDescription") );\n    progressDescription->setAlignment( Qt::AlignCenter );\n    progressDescription->setWordWrap( true );\n    progressLayout->addWidget( progressDescription );\n\n    auto* progressStages = new QLabel(\n        QStringLiteral(\n            "Preparing the drive   ·   Copying Bitcoin Core Vault   ·   "\n            "Configuring startup   ·   Checking the installation" ),\n        progressPanel );\n    progressStages->setObjectName( QStringLiteral("coreOfflineExecutionStages") );\n    progressStages->setAlignment( Qt::AlignCenter );\n    progressStages->setWordWrap( true );\n    progressLayout->addWidget( progressStages );\n\n    progressLayout->addStretch();\n\n    m_tab_widget->addTab( progressPanel, QStringLiteral("Progress") );','branded execution panel')
    execution=once(execution,'        "Toggle log" );','        "Show technical log" );','technical log wording')
    execution=once(execution,'    auto toggleLogButton = dynamic_cast< QToolButton* >( toolBar->widgetForAction( toggleLogAction ) );\n    connect( toggleLogButton, &QToolButton::clicked, this, &ExecutionViewStep::toggleLog );','    auto toggleLogButton = dynamic_cast< QToolButton* >( toolBar->widgetForAction( toggleLogAction ) );\n    toggleLogAction->setObjectName( QStringLiteral("coreOfflineToggleLogAction") );\n    toggleLogButton->setObjectName( QStringLiteral("coreOfflineToggleLog") );\n    toolBar->setToolButtonStyle( Qt::ToolButtonTextOnly );\n    connect( toggleLogButton, &QToolButton::clicked, this, &ExecutionViewStep::toggleLog );','technical log control')
    execution=once(execution,'    m_slideshow->changeSlideShowState( Slideshow::Start );','    m_slideshow->widget()->hide(); // CORE_OFFLINE_INTEGRATION: branded progress panel replaces slideshow.','disable slideshow canvas')
    execution=once(execution,'    m_tab_widget->setCurrentIndex( logBecomesVisible ? 1 : 0 );','    m_tab_widget->setCurrentIndex( logBecomesVisible ? 1 : 0 );\n    if ( auto* action = m_widget->findChild< QAction* >(\n             QStringLiteral("coreOfflineToggleLogAction") ) )\n    {\n        action->setText(\n            logBecomesVisible\n                ? QStringLiteral("Hide technical log")\n                : QStringLiteral("Show technical log") );\n    }','dynamic technical log wording')
    if not check_only:
        execution_path.write_text(execution)

    # Fail closed after all anchors validate.
    if check_only:
        print('BITCOIN CORE OFFLINE INSTALLER UX SOURCE CHECK PASSED')
        return
    for name,p in paths.items(): p.write_text(texts[name])
    shutil.copyfile(header,src/'src/modules/partition/core/CoreOfflineGuard.h')
    print('BITCOIN CORE OFFLINE INSTALLER UX SOURCE PATCH APPLIED')

if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('source',type=Path); a.add_argument('--header',type=Path,default=Path(__file__).with_name('CoreOfflineGuard.h')); a.add_argument('--check',action='store_true')
    o=a.parse_args(); patch(o.source,o.header,check_only=o.check)
