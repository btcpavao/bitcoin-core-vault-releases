// SPDX-License-Identifier: GPL-3.0-or-later
// A read-only pre-write check of the complete native partition job plan.
#pragma once
#include "Job.h"
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QProcess>
#include <QStringList>
static QMap<QString,QByteArray> coreOfflineDiskIdentity;
static QByteArray coreOfflineProbe(const QString& node)
{
    QProcess p;
    p.start(QStringLiteral("/usr/bin/python3"),{QStringLiteral("/usr/lib/core-vault-installer/disk_safety.py"),QStringLiteral("probe"),node});
    if(!p.waitForStarted(5000) || !p.waitForFinished(15000)) {p.kill();p.waitForFinished(1000);return {};}
    if(p.exitStatus()!=QProcess::NormalExit || p.exitCode()!=0) return {};
    return p.readAllStandardOutput().trimmed();
}
static QString coreOfflineValidate(const QJsonObject& plan,bool record=false)
{
    QProcess p; QStringList args{QStringLiteral("/usr/lib/core-vault-installer/disk_safety.py"),QStringLiteral("validate-plan")};
    if(record) args.append(QStringLiteral("--record"));
    p.start(QStringLiteral("/usr/bin/python3"),args);
    if(!p.waitForStarted(5000)) return QStringLiteral("The installation safety check could not start.");
    p.write(QJsonDocument(plan).toJson(QJsonDocument::Compact));p.closeWriteChannel();
    if(!p.waitForFinished(20000)) {p.kill();p.waitForFinished(1000);return QStringLiteral("The installation safety check timed out. No partition job was started.");}
    if(p.exitStatus()!=QProcess::NormalExit || p.exitCode()!=0) {
        const auto message=QString::fromUtf8(p.readAllStandardError()).trimmed();
        return message.isEmpty()?QStringLiteral("The installation plan could not be verified. No partition job was started."):message;
    }
    if(!QJsonDocument::fromJson(p.readAllStandardOutput()).object().value(QStringLiteral("ok")).toBool())
        return QStringLiteral("The installation safety check returned an invalid result.");
    return {};
}
class CoreOfflineDiskGuard : public Calamares::Job
{
public:
    explicit CoreOfflineDiskGuard(QJsonObject plan):m_plan(plan){}
    QString prettyName() const override {return QStringLiteral("Verify the selected disk and every planned partition operation");}
    QString prettyStatusMessage() const override {return prettyName();}
    Calamares::JobResult exec() override {
        const auto error=coreOfflineValidate(m_plan,true);
        return error.isEmpty()?Calamares::JobResult::ok():Calamares::JobResult::error(QStringLiteral("Installation stopped before partitioning"),error);
    }
private: QJsonObject m_plan;
};
